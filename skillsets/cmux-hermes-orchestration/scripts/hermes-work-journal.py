#!/usr/bin/env python3
"""Durable Hermes work journals (remote, long-work).

Stdlib-only helper that maintains per-task durable journals on the remote Hermes
host. Each task gets a private directory under the configured root: an atomic
JSON state file and an append-only markdown event log. The tool never makes a
network call, never reads or serializes environment *values*, and provides no
delete path — journals only move forward (start -> append -> heartbeat ->
checkpoint -> resume -> close).

Layout::

    <root>/                 # 0700, HERMES_WORK_JOURNAL_DIR (default
                            #        /var/lib/hermes/work-journals)
      <task-id>/            # 0700
        state.json          # 0600, atomic JSON state
        journal.md          # 0600, append-only markdown events
        .lock               # 0600, fcntl flock guard

Commands: start, append, heartbeat, checkpoint, show, list, resume, close,
selftest.

Design invariants (do not weaken):
  * No secrets: high-confidence secret signatures are always refused. There is
    no override. The tool never stores environment values.
  * Task IDs are allowlisted slugs only.
  * State writes are atomic (temp file in the same dir + os.replace), mode 0600.
  * Every write is serialized under an exclusive fcntl flock on the task lock.
  * There is no delete command and no truncation of journal.md.
  * Root and task directories are 0700; all files are 0600.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import sys
import tempfile
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DEFAULT_ROOT = os.environ.get(
    "HERMES_WORK_JOURNAL_DIR", "/var/lib/hermes/work-journals"
)

DIR_MODE = 0o700
FILE_MODE = 0o600
MAX_MESSAGE_BYTES = 32 * 1024
MAX_JOURNAL_BYTES = 8 * 1024 * 1024
MAX_CHECKPOINTS = 256

# Allowlisted task IDs: lowercase slug, 1-64 chars.
TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

# Event types aligned with SESSION_JOURNALING.md.
EVENT_TYPES = (
    "action", "decision", "issue", "result", "heartbeat", "checkpoint", "close"
)

SECRET_KEY_RE = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|client[_-]?secret|bearer|authorization)"
    r"\s*[:=]\s*\S+"
)
SECRET_AWS_RE = re.compile(r"AKIA[0-9A-Z]{16}")
SECRET_GITHUB_RE = re.compile(r"gh[pousr]_[A-Za-z0-9]{36}")
SECRET_PEM_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
SECRET_PROVIDER_RE = re.compile(
    r"(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,}|"
    r"xox[baprs]-[0-9A-Za-z-]{10,})"
)
SECRET_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
SECRET_URL_RE = re.compile(r"(?i)(?:https?://[^/\s:@]+:[^@\s/]+@|[?&](?:token|api[_-]?key|secret|password)=[^&\s]+)")


class JournalError(Exception):
    """Raised for recoverable, fail-closed conditions."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _validate_task_id(task_id: str) -> str:
    if not TASK_ID_RE.match(task_id or ""):
        raise JournalError(
            "task id must match [a-z0-9][a-z0-9-]{0,63} (allowlisted slug)"
        )
    return task_id


def _ensure_root(root: Path) -> None:
    if root.is_symlink():
        raise JournalError("journal root must not be a symlink")
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, DIR_MODE)
    except PermissionError as exc:
        raise JournalError(f"cannot tighten root perms: {exc}") from exc


def _task_dir(root: Path, task_id: str) -> Path:
    _validate_task_id(task_id)
    task_dir = root / task_id
    if task_dir.is_symlink():
        raise JournalError("task directory must not be a symlink")
    return task_dir


@contextmanager
def task_lock(task_dir: Path) -> Iterator[int]:
    """Exclusive fcntl flock on the task's .lock file."""
    if task_dir.is_symlink():
        raise JournalError("task directory must not be a symlink")
    task_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(task_dir, DIR_MODE)
    except PermissionError as exc:
        raise JournalError(f"cannot tighten task dir perms: {exc}") from exc
    dir_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        dir_fd = os.open(task_dir, dir_flags)
    except OSError as exc:
        raise JournalError(f"cannot safely open task directory: {exc}") from exc
    lock_flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(".lock", lock_flags, FILE_MODE, dir_fd=dir_fd)
    except OSError as exc:
        os.close(dir_fd)
        raise JournalError(f"cannot safely open task lock: {exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise JournalError("task lock is not a regular file")
        os.fchmod(fd, FILE_MODE)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield dir_fd
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        os.close(dir_fd)


def _atomic_write_json(dir_fd: int, data: dict[str, Any]) -> None:
    tmp_name = f".state-{secrets.token_hex(12)}"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp_name, flags, FILE_MODE, dir_fd=dir_fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(tmp_name, "state.json", src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except BaseException:
        try:
            os.unlink(tmp_name, dir_fd=dir_fd)
        except OSError:
            pass
        raise


def _load_state(dir_fd: int) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open("state.json", flags, dir_fd=dir_fd)
    except FileNotFoundError as exc:
        raise JournalError("task has no state.json; start it first") from exc
    except OSError as exc:
        raise JournalError(f"cannot safely open state.json: {exc}") from exc
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise JournalError("state.json is not a regular file")
        return json.load(handle)


def _save_state(dir_fd: int, state: dict[str, Any]) -> None:
    _atomic_write_json(dir_fd, state)


def _state_exists(dir_fd: int) -> bool:
    try:
        info = os.stat("state.json", dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode):
        raise JournalError("state.json is not a regular file")
    return True


def _read_journal(dir_fd: int) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open("journal.md", flags, dir_fd=dir_fd)
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise JournalError(f"cannot safely open journal.md: {exc}") from exc
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise JournalError("journal.md is not a regular file")
        return handle.read(MAX_JOURNAL_BYTES + 1)


def _append_markdown(dir_fd: int, etype: str, text: str) -> str:
    """Append an event to journal.md (mode 0600). Returns the timestamp."""
    ts = _utc_now()
    safe_type = etype if etype in EVENT_TYPES else "action"
    block = f"\n## {ts} - {safe_type}\n\n{text.strip()}\n"
    flags = os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open("journal.md", flags, FILE_MODE, dir_fd=dir_fd)
    except OSError as exc:
        raise JournalError(f"cannot safely open journal.md: {exc}") from exc
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise JournalError("journal.md is not a regular file")
        if info.st_size + len(block.encode("utf-8")) > MAX_JOURNAL_BYTES:
            raise JournalError("journal size limit reached")
        handle.write(block)
        handle.flush()
        os.fsync(handle.fileno())
        os.fchmod(handle.fileno(), FILE_MODE)
    return ts


def looks_secret(text: str) -> str | None:
    """Return a reason string if text matches a high-confidence secret shape."""
    for name, pattern in (
        ("key/secret assignment", SECRET_KEY_RE),
        ("AWS access key id", SECRET_AWS_RE),
        ("GitHub token", SECRET_GITHUB_RE),
        ("PEM private key", SECRET_PEM_RE),
        ("provider credential", SECRET_PROVIDER_RE),
        ("JWT", SECRET_JWT_RE),
        ("credential-bearing URL", SECRET_URL_RE),
    ):
        if pattern.search(text or ""):
            return name
    return None


def resolve_message(args: argparse.Namespace) -> str:
    """Resolve a message from --message (literal or '-' for stdin)."""
    raw = getattr(args, "message", None)
    if raw is None:
        return ""
    if raw == "-":
        return sys.stdin.read(MAX_MESSAGE_BYTES + 1)
    return raw


def _gate_secrets(text: str) -> None:
    if len((text or "").encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise JournalError(f"message exceeds {MAX_MESSAGE_BYTES} bytes")
    reason = looks_secret(text)
    if reason:
        raise JournalError(
            f"refusing to store likely secret ({reason}); strip it"
        )


def _require_active(state: dict[str, Any]) -> None:
    if state.get("status") == "closed":
        raise JournalError("task is closed; resume it before appending")


def cmd_start(root: Path, args: argparse.Namespace) -> int:
    task_dir = _task_dir(root, args.task_id)
    goal = resolve_message(args)
    _gate_secrets(goal)
    with task_lock(task_dir) as dir_fd:
        if _state_exists(dir_fd):
            raise JournalError(f"task {args.task_id!r} already exists")
        state = {
            "task_id": args.task_id,
            "status": "active",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "last_heartbeat_at": None,
            "goal": goal.strip(),
            "resume": {
                "phase": "started",
                "next_step": "",
                "validation": "not_run",
                "residual_risk": "",
            },
            "checkpoints": [],
            "events": 0,
        }
        _save_state(dir_fd, state)
        ts = _append_markdown(dir_fd, "action", f"Started. {goal.strip()}".strip())
        state["updated_at"] = ts
        state["events"] = 1
        _save_state(dir_fd, state)
    print(f"started {args.task_id}")
    return 0


def cmd_append(root: Path, args: argparse.Namespace) -> int:
    task_dir = _task_dir(root, args.task_id)
    text = resolve_message(args)
    _gate_secrets(text)
    with task_lock(task_dir) as dir_fd:
        state = _load_state(dir_fd)
        _require_active(state)
        ts = _append_markdown(dir_fd, args.type, text)
        state["updated_at"] = ts
        state["events"] = int(state.get("events", 0)) + 1
        _save_state(dir_fd, state)
    print(f"appended {args.type} to {args.task_id}")
    return 0


def cmd_checkpoint(root: Path, args: argparse.Namespace) -> int:
    task_dir = _task_dir(root, args.task_id)
    text = resolve_message(args)
    resume = {
        "phase": (args.phase or "").strip(),
        "next_step": (args.next_step or "").strip(),
        "validation": (args.validation or "not_run").strip(),
        "residual_risk": (args.residual_risk or "").strip(),
    }
    _gate_secrets("\n".join([text, *resume.values()]))
    with task_lock(task_dir) as dir_fd:
        state = _load_state(dir_fd)
        _require_active(state)
        ts = _append_markdown(dir_fd, "checkpoint", text or "(checkpoint)")
        cp = {"at": ts, "note": (text or "").strip()[:200], **resume}
        cps = list(state.get("checkpoints", []))
        cps.append(cp)
        if len(cps) > MAX_CHECKPOINTS:
            cps = cps[-MAX_CHECKPOINTS:]
        state["checkpoints"] = cps
        state["resume"] = resume
        state["updated_at"] = ts
        state["events"] = int(state.get("events", 0)) + 1
        _save_state(dir_fd, state)
    print(f"checkpoint {args.task_id} @ {ts}")
    return 0


def cmd_heartbeat(root: Path, args: argparse.Namespace) -> int:
    task_dir = _task_dir(root, args.task_id)
    text = resolve_message(args)
    phase = (args.phase or "").strip()
    next_step = (args.next_step or "").strip()
    _gate_secrets("\n".join((text, phase, next_step)))
    with task_lock(task_dir) as dir_fd:
        state = _load_state(dir_fd)
        _require_active(state)
        detail = text.strip() or "work is still active"
        ts = _append_markdown(dir_fd, "heartbeat", detail)
        resume = dict(state.get("resume") or {})
        if phase:
            resume["phase"] = phase
        if next_step:
            resume["next_step"] = next_step
        state["resume"] = resume
        state["last_heartbeat_at"] = ts
        state["updated_at"] = ts
        state["events"] = int(state.get("events", 0)) + 1
        _save_state(dir_fd, state)
    print(f"heartbeat {args.task_id} @ {ts}")
    return 0


def cmd_resume(root: Path, args: argparse.Namespace) -> int:
    task_dir = _task_dir(root, args.task_id)
    text = resolve_message(args)
    _gate_secrets(text)
    with task_lock(task_dir) as dir_fd:
        state = _load_state(dir_fd)
        prev = state.get("status")
        ts = _append_markdown(
            dir_fd, "action", f"Resumed (was {prev}). {text.strip()}".strip()
        )
        state["status"] = "active"
        state["updated_at"] = ts
        state["events"] = int(state.get("events", 0)) + 1
        _save_state(dir_fd, state)
    print(f"resumed {args.task_id}")
    return 0


def cmd_close(root: Path, args: argparse.Namespace) -> int:
    task_dir = _task_dir(root, args.task_id)
    text = resolve_message(args)
    _gate_secrets(text)
    with task_lock(task_dir) as dir_fd:
        state = _load_state(dir_fd)
        ts = _append_markdown(dir_fd, "close", text or "(closed)")
        state["status"] = "closed"
        state["updated_at"] = ts
        state["events"] = int(state.get("events", 0)) + 1
        _save_state(dir_fd, state)
    print(f"closed {args.task_id}")
    return 0


def cmd_show(root: Path, args: argparse.Namespace) -> int:
    task_dir = _task_dir(root, args.task_id)
    with task_lock(task_dir) as dir_fd:
        state = _load_state(dir_fd)
        journal = _read_journal(dir_fd)
    print(json.dumps(state, indent=2, sort_keys=True))
    sys.stdout.write("\n--- journal.md ---\n")
    sys.stdout.write(journal)
    if not journal.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def cmd_list(root: Path, args: argparse.Namespace) -> int:
    if not root.exists():
        print(json.dumps({"tasks": []}, indent=2))
        return 0
    tasks = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not TASK_ID_RE.match(entry.name):
            continue
        try:
            with task_lock(entry) as dir_fd:
                state = _load_state(dir_fd)
            tasks.append(
                {
                    "task_id": state.get("task_id", entry.name),
                    "status": state.get("status"),
                    "updated_at": state.get("updated_at"),
                    "events": state.get("events", 0),
                }
            )
        except (JournalError, json.JSONDecodeError):
            continue
    print(json.dumps({"tasks": tasks}, indent=2, sort_keys=True))
    return 0


def selftest() -> int:
    """Offline tests in a temp root. No network, no real /var/lib writes."""
    tmp = Path(tempfile.mkdtemp(prefix="hermes-journal-test-"))
    root = tmp / "journals"
    results: list[tuple[str, bool, str]] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        results.append((name, cond, detail))
        print(f"[{'ok' if cond else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))

    # start
    check("start returns 0", cmd_start(root, argparse.Namespace(
        task_id="feat-x", message="Wire durable journals")) == 0)
    td = root / "feat-x"
    check("state.json exists", (td / "state.json").exists())
    check("state is 0600", oct((td / "state.json").stat().st_mode & 0o777) == "0o600")
    check("task dir is 0700", oct(td.stat().st_mode & 0o777) == "0o700")
    check("journal.md exists", (td / "journal.md").exists())

    # duplicate start blocked
    try:
        cmd_start(root, argparse.Namespace(
            task_id="feat-x", message="dup"))
        check("duplicate start blocked", False)
    except JournalError:
        check("duplicate start blocked", True)

    # bad task id blocked
    try:
        cmd_start(root, argparse.Namespace(
            task_id="../escape", message="x"))
        check("bad task id blocked", False)
    except JournalError:
        check("bad task id blocked", True)

    # append + checkpoint
    check("append action", cmd_append(root, argparse.Namespace(
        task_id="feat-x", message="Implemented atomic write", type="action")) == 0)
    check("append decision", cmd_append(root, argparse.Namespace(
        task_id="feat-x", message="chose os.replace for atomicity", type="decision")) == 0)
    check("heartbeat", cmd_heartbeat(root, argparse.Namespace(
        task_id="feat-x", message="running validation", phase="validate",
        next_step="record checkpoint")) == 0)
    check("checkpoint", cmd_checkpoint(root, argparse.Namespace(
        task_id="feat-x", message="state + journal wired", phase="validate",
        next_step="close canary", validation="pass", residual_risk="none")) == 0)

    # secret refusal (clearly-fake, non-real value that triggers the key-shape gate)
    try:
        cmd_append(root, argparse.Namespace(
            task_id="feat-x", message="api_key=EXAMPLE-NOT-A-REAL-SECRET", type="action"))
        check("secret append refused", False)
    except JournalError:
        check("secret append refused", True)

    provider_shapes = [
        "sk-" + "x" * 24,
        "sk-ant-" + "y" * 24,
        "AIza" + "z" * 24,
        "xoxb-" + "1" * 20,
        "https://user:password@example.invalid/path",
        "eyJ" + "a" * 10 + "." + "b" * 10 + "." + "c" * 10,
    ]
    check("common credential shapes detected",
          all(looks_secret(value) for value in provider_shapes))
    try:
        _gate_secrets("x" * (MAX_MESSAGE_BYTES + 1))
        check("oversized message refused", False)
    except JournalError:
        check("oversized message refused", True)

    # A same-user process must not redirect journal writes through a symlink.
    check("start symlink canary", cmd_start(root, argparse.Namespace(
        task_id="symlink-x", message="symlink safety")) == 0)
    victim = tmp / "victim.txt"
    victim.write_text("unchanged", encoding="utf-8")
    symlink_journal = root / "symlink-x" / "journal.md"
    symlink_journal.unlink()
    symlink_journal.symlink_to(victim)
    try:
        cmd_append(root, argparse.Namespace(
            task_id="symlink-x", message="must not escape", type="action"))
        check("journal symlink refused", False)
    except JournalError:
        check("journal symlink refused", victim.read_text(encoding="utf-8") == "unchanged")

    # close then append blocked, then resume reopens
    check("close", cmd_close(root, argparse.Namespace(
        task_id="feat-x", message="done")) == 0)
    try:
        cmd_append(root, argparse.Namespace(
            task_id="feat-x", message="after close", type="action"))
        check("append after close blocked", False)
    except JournalError:
        check("append after close blocked", True)
    check("resume", cmd_resume(root, argparse.Namespace(
        task_id="feat-x", message="revisit")) == 0)

    # list
    import io
    buf = io.StringIO()
    saved = sys.stdout
    sys.stdout = buf
    rc = cmd_list(root, argparse.Namespace())
    sys.stdout = saved
    listing = buf.getvalue()
    check("list returns 0", rc == 0)
    check("list includes feat-x", '"feat-x"' in listing and '"active"' in listing)

    # atomic state validity
    with task_lock(td) as dir_fd:
        state = _load_state(dir_fd)
    check("state valid json with events>0", int(state.get("events", 0)) > 0)
    check("state has checkpoints", len(state.get("checkpoints", [])) >= 1)
    check("heartbeat persisted", bool(state.get("last_heartbeat_at")))
    check("resume packet persisted", state.get("resume", {}).get("next_step") == "close canary")

    # append-only: journal has multiple event headers
    body = (td / "journal.md").read_text(encoding="utf-8")
    check("journal append-only (>=4 events)", body.count("\n## ") >= 4)

    # show
    buf2 = io.StringIO()
    sys.stdout = buf2
    cmd_show(root, argparse.Namespace(task_id="feat-x"))
    sys.stdout = saved
    check("show emits state + journal", '"task_id": "feat-x"' in buf2.getvalue())

    # perms tightened on journal after appends
    check("journal.md is 0600", oct((td / "journal.md").stat().st_mode & 0o777) == "0o600")

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hermes-work-journal.py",
        description="Durable Hermes work journals (atomic state + append-only log).",
    )
    parser.add_argument(
        "--root",
        default=DEFAULT_ROOT,
        help=f"journal root (default {DEFAULT_ROOT}; env HERMES_WORK_JOURNAL_DIR)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_task(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("task_id")
        sp.add_argument("--message", default=None,
                        help="event text, or '-' to read from stdin")

    p = sub.add_parser("start", help="create a new task journal"); add_task(p)
    p = sub.add_parser("append", help="append an event"); add_task(p)
    p.add_argument("--type", default="action", choices=EVENT_TYPES)
    p = sub.add_parser("heartbeat", help="record liveness and current phase"); add_task(p)
    p.add_argument("--phase", default="")
    p.add_argument("--next-step", default="")
    p = sub.add_parser("checkpoint", help="record a structured resume checkpoint"); add_task(p)
    p.add_argument("--phase", default="")
    p.add_argument("--next-step", default="")
    p.add_argument("--validation", default="not_run",
                   choices=("pass", "fail", "blocked", "skipped", "not_run"))
    p.add_argument("--residual-risk", default="")
    p = sub.add_parser("resume", help="reopen a paused/closed task"); add_task(p)
    p = sub.add_parser("close", help="close a task (no delete)"); add_task(p)
    sub.add_parser("show", help="print a task's state and journal").add_argument("task_id")
    sub.add_parser("list", help="list task journals")
    sub.add_parser("selftest", help="run offline tests in a temp dir")
    return parser


COMMANDS = {
    "start": cmd_start,
    "append": cmd_append,
    "heartbeat": cmd_heartbeat,
    "checkpoint": cmd_checkpoint,
    "resume": cmd_resume,
    "close": cmd_close,
    "show": cmd_show,
    "list": cmd_list,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "selftest":
        return selftest()

    try:
        requested_root = Path(args.root).expanduser()
        if requested_root.is_symlink():
            raise JournalError("journal root must not be a symlink")
        root = requested_root.resolve(strict=False)
        _ensure_root(root)
        handler = COMMANDS.get(args.command)
        if handler is None:
            parser.error(f"unknown command {args.command!r}")
        return handler(root, args)
    except JournalError as exc:
        sys.stderr.write(f"hermes-work-journal: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
