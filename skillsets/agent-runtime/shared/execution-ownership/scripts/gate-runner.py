#!/usr/bin/env python3
"""Durable, fail-closed state machine for expensive gates and reviews.

This is intentionally separate from execution-ownership.py.  The lease is
ephemeral concurrency control; this ledger persists what already ran so a
later agent cannot honestly start the same successful gate again.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = 1
STALE_AFTER = 900.0
REVIEW_DEFAULT = 300.0
REVIEW_MAX = 900.0
ID_RE = re.compile(r"^[0-9a-f]{32}$")
HEX_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
EXIT_OK = 0
EXIT_HELD = 10
EXIT_ALREADY_PASSED = 20
EXIT_REPAIR_REQUIRED = 21
EXIT_INVALID = 2
EXIT_TIMED_OUT = 25
EXIT_STALE = 26
EXIT_STATE = 14


class GuardError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = EXIT_STATE):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


def now_iso(value: float | None = None) -> str:
    return datetime.fromtimestamp(value if value is not None else time.time(), timezone.utc).replace(microsecond=0).isoformat()


def text(value: Any, name: str, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum or value != value.strip():
        raise GuardError("invalid_argument", f"{name} must be non-empty text", EXIT_INVALID)
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in value):
        raise GuardError("invalid_argument", f"{name} contains control characters", EXIT_INVALID)
    return value


def directory(value: Any, name: str) -> str:
    raw = text(value, name)
    path = Path(raw)
    if not path.is_absolute():
        raise GuardError("invalid_target", f"{name} must be absolute", EXIT_INVALID)
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise GuardError("invalid_target", f"cannot inspect {name}: {exc}", EXIT_INVALID)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise GuardError("invalid_target", f"{name} must be a real directory", EXIT_INVALID)
    return os.path.normcase(os.path.realpath(path))


def target(args: argparse.Namespace) -> dict[str, str]:
    commit = text(args.commit, "commit", 64)
    if not HEX_RE.fullmatch(commit):
        raise GuardError("invalid_target", "commit must be 7-64 hexadecimal characters", EXIT_INVALID)
    result = {
        "repo": directory(args.repo, "repo"),
        "worktree": directory(args.worktree, "worktree"),
        "branch": text(args.branch, "branch", 256),
        "commit": commit.lower(),
        "gate": text(args.gate, "gate", 256),
    }
    return result


def target_key(value: dict[str, str]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class Store:
    def __init__(self, root: Path | str | None = None, clock: Any = time.time):
        if root is None:
            base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
            root = Path(base) / "ai-config-kit" / "gate-runs"
        self.root = Path(root)
        self.clock = clock

    def _secure_root(self) -> Path:
        if not self.root.is_absolute() or self.root.is_symlink():
            raise GuardError("unsafe_root", "state root must be an absolute, non-symlink directory")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            info = os.lstat(self.root)
        except OSError as exc:
            raise GuardError("state_root", f"cannot create state root: {exc}")
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise GuardError("unsafe_root", "state root must be a real directory")
        os.chmod(self.root, 0o700)
        return self.root

    @contextmanager
    def locked(self) -> Iterator[None]:
        root = self._secure_root()
        fd = os.open(root / ".lock", os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def path(self, run_id: str) -> Path:
        if not ID_RE.fullmatch(run_id):
            raise GuardError("invalid_run_id", "run-id is not valid", EXIT_INVALID)
        return self.root / f"run-{run_id}.json"

    def read(self, run_id: str) -> dict[str, Any]:
        path = self.path(run_id)
        try:
            info = os.lstat(path)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise GuardError("unsafe_state", "run state must be a regular file")
            if stat.S_IMODE(info.st_mode) != 0o600:
                raise GuardError("unsafe_state", "run state permissions must be 0600")
            with path.open(encoding="utf-8") as handle:
                state = json.load(handle)
        except FileNotFoundError:
            raise GuardError("missing_run", "run does not exist", EXIT_INVALID)
        except GuardError:
            raise
        except (OSError, json.JSONDecodeError) as exc:
            raise GuardError("malformed_state", f"run state is unreadable: {exc}")
        if not isinstance(state, dict) or state.get("schema") != SCHEMA:
            raise GuardError("malformed_state", "unsupported run state")
        return state

    def write(self, state: dict[str, Any]) -> None:
        path = self.path(state["run_id"])
        tmp = self.root / f".run-{state['run_id']}.{os.getpid()}.tmp"
        payload = (json.dumps(state, sort_keys=True, indent=2) + "\n").encode()
        fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass

    def all_states(self) -> list[dict[str, Any]]:
        self._secure_root()
        states = []
        for path in sorted(self.root.glob("run-*.json")):
            if path.is_symlink() or not path.is_file():
                raise GuardError("unsafe_state", f"unsafe run file: {path}")
            states.append(self.read(path.stem.removeprefix("run-")))
        return states

    def active_stale(self, state: dict[str, Any]) -> bool:
        return state.get("status") == "active" and self.clock() - float(state["last_checkpoint_unix"]) > STALE_AFTER


def evidence(args: argparse.Namespace) -> dict[str, Any]:
    command = text(args.command, "command", 4096)
    measurement = text(args.measurement, "measurement", 4096)
    artifact = Path(text(args.artifact, "artifact", 4096))
    if not artifact.is_absolute() or artifact.is_symlink() or not artifact.is_file():
        raise GuardError("missing_artifact", "artifact must be an existing regular file", EXIT_INVALID)
    return {"command": command, "measurement": measurement, "artifact": str(artifact), "at": now_iso()}


def output(value: dict[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True))


def cmd_start(store: Store, args: argparse.Namespace) -> int:
    t = target(args)
    with store.locked():
        for prior in store.all_states():
            if prior["target_key"] != target_key(t) or prior["gate"]["name"] != t["gate"]:
                continue
            status = prior["gate"]["status"]
            if status == "passed":
                output({"status": "already_passed", "run_id": prior["run_id"], "exit_code": EXIT_ALREADY_PASSED})
                return EXIT_ALREADY_PASSED
            if status == "running":
                output({"status": "held", "run_id": prior["run_id"], "exit_code": EXIT_HELD})
                return EXIT_HELD
            if status in {"failed", "timed_out"}:
                output({"status": "repair_required", "run_id": prior["run_id"], "exit_code": EXIT_REPAIR_REQUIRED})
                return EXIT_REPAIR_REQUIRED
        run_id = secrets.token_hex(16)
        stamp = now_iso(store.clock())
        state = {
            "schema": SCHEMA, "run_id": run_id, "target": t, "target_key": target_key(t), "gate": {
                "name": t["gate"], "status": "running", "attempts": 1, "started_at": stamp,
            }, "review": None, "status": "active", "started_at": stamp,
            "last_checkpoint_at": stamp, "last_checkpoint_unix": store.clock(),
            "checkpoints": [], "owner": {"pid": os.getpid(), "owner_thread": os.environ.get("BB_THREAD_ID")},
        }
        store.write(state)
    output({"status": "started", "run_id": run_id, "attempt": 1, "exit_code": EXIT_OK})
    return EXIT_OK


def cmd_adopt(store: Store, args: argparse.Namespace) -> int:
    """Persist an already completed gate without rerunning it."""
    t = target(args)
    item = evidence(args)
    with store.locked():
        for prior in store.all_states():
            if prior["target_key"] != target_key(t) or prior["gate"]["name"] != t["gate"]:
                continue
            if prior["gate"]["status"] == "passed":
                output({"status": "already_passed", "run_id": prior["run_id"], "exit_code": EXIT_ALREADY_PASSED})
                return EXIT_ALREADY_PASSED
            raise GuardError("existing_run", "a prior run exists; inspect or repair it instead of adopting over it", EXIT_HELD)
        run_id = secrets.token_hex(16)
        stamp = now_iso(store.clock())
        state = {
            "schema": SCHEMA, "run_id": run_id, "target": t, "target_key": target_key(t), "gate": {
                "name": t["gate"], "status": "passed", "attempts": 1, "started_at": stamp,
                "finished_at": stamp, "exit_code": 0, "evidence": item, "adopted": True,
            }, "review": None, "status": "active", "started_at": stamp,
            "last_checkpoint_at": stamp, "last_checkpoint_unix": store.clock(), "checkpoints": [],
            "owner": {"pid": os.getpid(), "owner_thread": os.environ.get("BB_THREAD_ID")},
        }
        store.write(state)
    output({"status": "adopted", "run_id": run_id, "attempt": 1, "exit_code": EXIT_OK})
    return EXIT_OK


def cmd_checkpoint(store: Store, args: argparse.Namespace) -> int:
    with store.locked():
        state = store.read(args.run_id)
        if state["status"] != "active":
            raise GuardError("closed_run", "cannot checkpoint a closed run", EXIT_INVALID)
        item = evidence(args)
        item.update({"phase": text(args.phase, "phase", 256), "at": now_iso(store.clock()), "unix": store.clock()})
        state["checkpoints"].append(item)
        state["last_checkpoint_at"] = item["at"]
        state["last_checkpoint_unix"] = item["unix"]
        store.write(state)
    output({"status": "checkpointed", "run_id": args.run_id, "phase": item["phase"], "exit_code": EXIT_OK})
    return EXIT_OK


def cmd_repair(store: Store, args: argparse.Namespace) -> int:
    with store.locked():
        state = store.read(args.run_id)
        gate = state["gate"]
        if gate["status"] not in {"failed", "timed_out"}:
            raise GuardError("repair_not_allowed", "repair is allowed only after failed or timed_out gate", EXIT_INVALID)
        if gate["attempts"] >= 2:
            raise GuardError("attempt_limit", "a gate has at most one repair rerun", EXIT_REPAIR_REQUIRED)
        repair_ref = text(args.repair_ref, "repair-ref", 4096)
        gate.update({"status": "running", "attempts": 2, "repair_ref": repair_ref, "repair_started_at": now_iso(store.clock())})
        state["last_checkpoint_at"] = now_iso(store.clock())
        state["last_checkpoint_unix"] = store.clock()
        store.write(state)
    output({"status": "repair_started", "run_id": args.run_id, "attempt": 2, "exit_code": EXIT_OK})
    return EXIT_OK


def cmd_finish(store: Store, args: argparse.Namespace) -> int:
    allowed = {"passed", "failed", "deferred", "timed_out"}
    if args.status not in allowed:
        raise GuardError("invalid_status", f"status must be one of {sorted(allowed)}", EXIT_INVALID)
    item = evidence(args)
    with store.locked():
        state = store.read(args.run_id)
        gate = state["gate"]
        if gate["status"] != "running":
            raise GuardError("invalid_transition", "gate is not running", EXIT_INVALID)
        if args.status == "passed" and args.exit_code != 0:
            raise GuardError("invalid_evidence", "passed gate requires exit-code 0", EXIT_INVALID)
        gate.update({"status": args.status, "finished_at": now_iso(store.clock()), "exit_code": args.exit_code, "evidence": item})
        state["last_checkpoint_at"] = item["at"]
        state["last_checkpoint_unix"] = store.clock()
        store.write(state)
    output({"status": args.status, "run_id": args.run_id, "attempt": gate["attempts"], "exit_code": EXIT_OK})
    return EXIT_OK


def cmd_review_start(store: Store, args: argparse.Namespace) -> int:
    timeout = float(args.timeout_seconds)
    if timeout <= 0 or timeout > REVIEW_MAX:
        raise GuardError("invalid_timeout", f"review timeout must be between 0 and {int(REVIEW_MAX)} seconds", EXIT_INVALID)
    with store.locked():
        state = store.read(args.run_id)
        if state["review"] and state["review"]["status"] == "waiting":
            raise GuardError("review_held", "review is already waiting", EXIT_HELD)
        started = store.clock()
        state["review"] = {"status": "waiting", "started_unix": started, "deadline_unix": started + timeout,
                            "started_at": now_iso(started), "deadline_at": now_iso(started + timeout), "timeout_seconds": timeout}
        state["last_checkpoint_at"] = now_iso(started)
        state["last_checkpoint_unix"] = started
        store.write(state)
    output({"status": "review_waiting", "run_id": args.run_id, "deadline_at": state["review"]["deadline_at"], "exit_code": EXIT_OK})
    return EXIT_OK


def cmd_review_check(store: Store, args: argparse.Namespace) -> int:
    with store.locked():
        state = store.read(args.run_id)
        review = state["review"]
        if not review or review["status"] != "waiting":
            raise GuardError("review_not_waiting", "review is not waiting", EXIT_INVALID)
        if store.clock() >= review["deadline_unix"]:
            timed_out_at = now_iso(store.clock())
            review.update({"status": "timed_out", "timed_out_at": timed_out_at})
            state["gate"].update({
                "status": "timed_out",
                "finished_at": timed_out_at,
                "exit_code": EXIT_TIMED_OUT,
                "evidence": {
                    "command": "review-check",
                    "measurement": "review deadline exceeded",
                    "artifact": "",
                    "at": timed_out_at,
                },
            })
            state["last_checkpoint_at"] = review["timed_out_at"]
            state["last_checkpoint_unix"] = store.clock()
            store.write(state)
            output({"status": "timed_out", "run_id": args.run_id, "exit_code": EXIT_TIMED_OUT})
            return EXIT_TIMED_OUT
        output({"status": "review_waiting", "run_id": args.run_id, "deadline_at": review["deadline_at"], "exit_code": EXIT_HELD})
        return EXIT_HELD


def reconcile_terminal_review(state: dict) -> bool:
    """Repair states written by versions that forgot to close the gate."""
    review = state.get("review")
    gate = state.get("gate")
    if not review or not gate or review.get("status") not in {"passed", "failed", "timed_out"}:
        return False
    if gate.get("status") != "running":
        return False
    finished_at = review.get("finished_at") or review.get("timed_out_at") or state.get("last_checkpoint_at")
    gate.update({
        "status": review["status"],
        "finished_at": finished_at,
        "exit_code": 0 if review["status"] == "passed" else (EXIT_TIMED_OUT if review["status"] == "timed_out" else 1),
        "evidence": review.get("evidence") or {
            "command": "review-check",
            "measurement": "reconciled terminal review state",
            "artifact": "",
            "at": finished_at,
        },
    })
    return True


def cmd_review_finish(store: Store, args: argparse.Namespace) -> int:
    if args.status not in {"passed", "failed"}:
        raise GuardError("invalid_status", "review status must be passed or failed", EXIT_INVALID)
    item = evidence(args)
    with store.locked():
        state = store.read(args.run_id)
        review = state["review"]
        if not review or review["status"] != "waiting":
            raise GuardError("invalid_transition", "review is not waiting", EXIT_INVALID)
        review.update({"status": args.status, "finished_at": item["at"], "evidence": item})
        state["gate"].update({"status": args.status, "finished_at": item["at"], "exit_code": 0 if args.status == "passed" else 1, "evidence": item})
        state["last_checkpoint_at"] = item["at"]
        state["last_checkpoint_unix"] = store.clock()
        store.write(state)
    output({"status": args.status, "run_id": args.run_id, "exit_code": EXIT_OK})
    return EXIT_OK


def cmd_status(store: Store, args: argparse.Namespace) -> int:
    with store.locked():
        state = store.read(args.run_id)
        if reconcile_terminal_review(state):
            store.write(state)
        stale = store.active_stale(state)
    result = {"status": "stale" if stale else state["status"], "run_id": args.run_id,
              "gate": state["gate"], "review": state["review"], "last_checkpoint_at": state["last_checkpoint_at"],
              "stale_after_seconds": STALE_AFTER, "exit_code": EXIT_STALE if stale else EXIT_OK}
    output(result)
    return EXIT_STALE if stale else EXIT_OK


def cmd_close(store: Store, args: argparse.Namespace) -> int:
    if args.outcome not in {"passed", "failed", "deferred", "timed_out"}:
        raise GuardError("invalid_status", "outcome must be passed, failed, deferred, or timed_out", EXIT_INVALID)
    item = evidence(args)
    with store.locked():
        state = store.read(args.run_id)
        if reconcile_terminal_review(state):
            store.write(state)
        if state["gate"]["status"] == "running" or (state["review"] and state["review"]["status"] == "waiting"):
            raise GuardError("active_work", "cannot close while a gate or review is running", EXIT_HELD)
        if state["gate"]["status"] != args.outcome:
            raise GuardError("outcome_mismatch", "close outcome must match the recorded gate status", EXIT_INVALID)
        state["status"] = "closed"
        state["closed_at"] = item["at"]
        state["outcome"] = args.outcome
        state["close_evidence"] = item
        store.write(state)
    output({"status": "closed", "run_id": args.run_id, "outcome": args.outcome, "exit_code": EXIT_OK})
    return EXIT_OK


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", help="test/state root")
    sub = p.add_subparsers(dest="action", required=True)
    for action in ("start", "adopt"):
        command = sub.add_parser(action)
        for name in ("repo", "worktree", "branch", "commit", "gate"):
            command.add_argument(f"--{name}", required=True)
        if action == "adopt":
            command.add_argument("--command", required=True)
            command.add_argument("--measurement", required=True)
            command.add_argument("--artifact", required=True)
    for name in ("checkpoint", "repair", "finish", "review-start", "review-check", "review-finish", "status", "close"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--run-id", required=True)
    checkpoint = sub.choices["checkpoint"]
    checkpoint.add_argument("--phase", required=True)
    repair = sub.choices["repair"]
    repair.add_argument("--repair-ref", required=True)
    finish = sub.choices["finish"]
    finish.add_argument("--status", required=True)
    review_start = sub.choices["review-start"]
    review_start.add_argument("--timeout-seconds", type=float, default=REVIEW_DEFAULT)
    review_finish = sub.choices["review-finish"]
    review_finish.add_argument("--status", required=True)
    close = sub.choices["close"]
    close.add_argument("--outcome", required=True)
    for name in ("checkpoint", "finish", "review-finish", "close"):
        cmd = sub.choices[name]
        cmd.add_argument("--command", required=True)
        cmd.add_argument("--measurement", required=True)
        cmd.add_argument("--artifact", required=True)
    sub.choices["finish"].add_argument("--exit-code", type=int, required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        store = Store(args.root)
        dispatch = {"start": cmd_start, "adopt": cmd_adopt, "checkpoint": cmd_checkpoint, "repair": cmd_repair, "finish": cmd_finish,
                    "review-start": cmd_review_start, "review-check": cmd_review_check, "review-finish": cmd_review_finish,
                    "status": cmd_status, "close": cmd_close}
        return dispatch[args.action](store, args)
    except GuardError as exc:
        output({"status": "error", "code": exc.code, "message": exc.message, "exit_code": exc.exit_code})
        return exc.exit_code
    except (OSError, ValueError, TypeError) as exc:
        output({"status": "error", "code": "state_error", "message": str(exc), "exit_code": EXIT_STATE})
        return EXIT_STATE


if __name__ == "__main__":
    raise SystemExit(main())
