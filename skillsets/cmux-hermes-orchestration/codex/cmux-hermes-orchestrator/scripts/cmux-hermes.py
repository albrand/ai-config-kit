#!/usr/bin/env python3
"""cmux-hermes deterministic broker.

Local, dependency-free helper that owns the safe boundary between the local
cmux session transport and the remote Hermes provider router. It never makes a
model inference on its own: it only shapes commands, validates arguments, keeps
task manifests, and reports. Noninteractive model calls fail closed because the
installed Hermes query interface exposes prompt text in process argv.

Design invariants (enforced everywhere, do not weaken):
  * No shell=True, no eval, no string interpolation of prompt/result text.
  * Prompt content is entered through the persistent remote terminal, not argv.
  * The full local environment is never forwarded to the remote host.
  * CMUX_SOCKET_CAPABILITY and CMUX_* are never serialized or forwarded.
  * Every remote command transitions noninteractively to user ``hermes`` with
    HOME set to /var/lib/hermes.
  * Hermes ``-z`` is never used (it auto-enables YOLO).
  * Write isolation is one task, one git worktree, one write owner.
  * Destructive actions fail closed; cleanup defaults to report-only.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import time
import uuid as uuidlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# --- Static, safe defaults -------------------------------------------------

DEFAULT_TARGET = os.environ.get("CMUX_HERMES_TARGET", "vps")
REMOTE_USER = "hermes"
REMOTE_HOME = "/var/lib/hermes"
REMOTE_WORKDIR = REMOTE_HOME
HERMES_BIN = "/opt/hermes/agent/venv/bin/hermes"

# Default operational bounds (overridable only by explicit flags/env).
DEFAULT_MAX_OUTPUT = int(os.environ.get("CMUX_HERMES_MAX_OUTPUT", "1024"))
DEFAULT_MAX_TURNS = int(os.environ.get("CMUX_HERMES_MAX_TURNS", "8"))
DEFAULT_MAX_PROMPT_BYTES = int(os.environ.get("CMUX_HERMES_MAX_PROMPT_BYTES", "32768"))
DEFAULT_CONCURRENCY = 1
DEFAULT_DEPTH = 1

# Validate every token placed on a remote argv. Static literals only; prompt
# text never appears here.
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SESSION_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,64}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")
PROVIDER_RE = re.compile(r"^[A-Za-z0-9._/-]{1,64}$")
TOOLSET_RE = re.compile(r"^(safe|no-terminal|none)$")
TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,254}$")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
INT_RE = re.compile(r"^[0-9]+$")

# Environment variables that must never be serialized or forwarded.
DENY_ENV_PATTERNS = ("CMUX_SOCKET_CAPABILITY",)
DENY_ENV_PREFIX = "CMUX_"


class BrokerError(Exception):
    """Raised for any recoverable, fail-closed condition."""


# --- Process execution -----------------------------------------------------


def _bin(env_var: str, default: str) -> str:
    """Resolve a CLI binary path. Override is for offline tests only."""
    candidate = os.environ.get(env_var, default)
    if not candidate:
        raise BrokerError(f"disabled binary via {env_var}")
    return candidate


def run(
    argv: Iterable[str],
    *,
    stdin: bytes | None = None,
    check: bool = False,
    capture: bool = True,
    timeout: int | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run argv as a list. Never shell=True. Never interpolates stdin."""
    argv = list(argv)
    if not argv:
        raise BrokerError("empty command")
    try:
        return subprocess.run(
            argv,
            input=stdin,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            check=check,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
    except FileNotFoundError as exc:
        raise BrokerError(f"missing binary for {argv[0]!r}: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise BrokerError(f"timeout running {argv[0]!r}") from exc


def _validate_remote_token(token: str, pattern: re.Pattern[str], label: str) -> str:
    if not pattern.match(token):
        raise BrokerError(f"unsafe {label}: {token!r}")
    return token


def _validate_target_policy(target: str) -> str:
    target = _validate_remote_token(target, TARGET_RE, "ssh target")
    allowed_targets = {
        item.strip() for item in os.environ.get("CMUX_HERMES_ALLOWED_TARGETS", "vps").split(",")
        if item.strip()
    }
    if target not in allowed_targets:
        raise BrokerError(f"ssh target {target!r} is not in CMUX_HERMES_ALLOWED_TARGETS")
    return target


def remote_argv(
    target: str,
    command: Iterable[str],
    *,
    tailscale_ip: str | None = None,
    host_key_alias: str | None = None,
) -> list[str]:
    """Build an ssh argv. Remote command is static validated tokens only.

    HOME/TMUX_TMPDIR are set with literal values; no local env is forwarded.
    The remote user is asserted separately (see assert_remote_user).
    """
    target = _validate_target_policy(target)
    cmd = [
        "sudo", "-n", "-u", REMOTE_USER,
        "env",
        f"HOME={REMOTE_HOME}",
        f"TMUX_TMPDIR={REMOTE_HOME}/.tmux",
        *command,
    ]
    # OpenSSH joins remote argv through the remote login shell. Quote every
    # token into one command string; prompt/result data never enters this list.
    argv = [
        _bin("SSH_BIN", "ssh"),
        "-o", "BatchMode=yes",
        "-o", "ForwardAgent=no",
        "-o", "ClearAllForwardings=yes",
        "-o", "PermitLocalCommand=no",
        "-o", "RequestTTY=no",
    ]
    if tailscale_ip:
        try:
            ipaddress.ip_address(tailscale_ip)
        except ValueError as exc:
            raise BrokerError("invalid Tailscale destination IP") from exc
        alias = host_key_alias or tailscale_ip
        if not re.fullmatch(r"[A-Za-z0-9.:-]{1,255}", alias):
            raise BrokerError("unsafe SSH host-key alias")
        argv.extend(["-o", f"HostName={tailscale_ip}", "-o", f"HostKeyAlias={alias}"])
    return [*argv, "--", target, shlex.join(cmd)]


def assert_tailnet_target(target: str) -> dict[str, Any]:
    """Bind the effective SSH destination to an online Tailscale peer."""
    target = _validate_target_policy(target)
    ssh_bin = _bin("SSH_BIN", "ssh")
    config = run([ssh_bin, "-G", "--", target], timeout=10)
    if config.returncode != 0:
        raise BrokerError(f"cannot resolve effective ssh config for {target!r}")
    ssh_config: dict[str, str] = {}
    for line in config.stdout.decode("utf-8", "replace").splitlines():
        key, _, value = line.partition(" ")
        ssh_config[key.lower()] = value.strip()
    hostname = ssh_config.get("hostname", "").lower().rstrip(".")
    if not hostname:
        raise BrokerError(f"ssh config for {target!r} has no effective hostname")
    for option in ("proxycommand", "proxyjump"):
        value = ssh_config.get(option, "none").strip().lower()
        if value not in ("", "none"):
            raise BrokerError(f"ssh {option} is forbidden for Tailscale-only targets")

    status = run([_bin("TAILSCALE_BIN", "tailscale"), "status", "--json"], timeout=15)
    if status.returncode != 0:
        raise BrokerError("tailscale status --json failed")
    try:
        network = json.loads(status.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise BrokerError("tailscale status returned invalid JSON") from exc
    peer_map = network.get("Peer") or {}
    peers = peer_map.values() if isinstance(peer_map, dict) else peer_map
    expected = os.environ.get("CMUX_HERMES_EXPECTED_TAILSCALE_PEER", "").strip().lower().rstrip(".")
    for peer in peers:
        if not isinstance(peer, dict) or peer.get("Online") is not True:
            continue
        identities = {
            str(peer.get("HostName") or "").lower().rstrip("."),
            str(peer.get("DNSName") or "").lower().rstrip("."),
            *(str(ip).lower() for ip in (peer.get("TailscaleIPs") or [])),
        }
        identities.discard("")
        tail_ips = [str(ip) for ip in (peer.get("TailscaleIPs") or [])]
        if hostname in identities and tail_ips and (not expected or expected in identities):
            forced_ip = next((ip for ip in tail_ips if ip.startswith("100.")), tail_ips[0])
            return {
                "target": target,
                "effective_hostname": hostname,
                "peer": peer.get("DNSName") or peer.get("HostName"),
                "tailscale_ips": tail_ips,
                "tailscale_ip": forced_ip,
            }
    detail = f" (expected peer {expected!r})" if expected else ""
    raise BrokerError(
        f"effective ssh hostname {hostname!r} is not an online Tailscale peer{detail}"
    )


def remote_run(
    target: str,
    command: Iterable[str],
    *,
    stdin: bytes | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    peer = assert_tailnet_target(target)
    return run(
        remote_argv(
            target,
            command,
            tailscale_ip=peer["tailscale_ip"],
            host_key_alias=peer["effective_hostname"],
        ),
        stdin=stdin,
        timeout=timeout,
    )


def assert_remote_user(target: str) -> None:
    """Fail closed unless the remote login is user ``hermes``."""
    proc = remote_run(target, ["id", "-un"], timeout=15)
    user = proc.stdout.decode("utf-8", "replace").strip()
    if user != REMOTE_USER:
        raise BrokerError(
            f"remote user is {user!r}, expected {REMOTE_USER!r} on target {target!r}"
        )


# --- Path safety -----------------------------------------------------------


def safe_abs_path(raw: str, *, base: Path | None = None) -> Path:
    """Reject non-absolute paths and symlink escapes outside base."""
    if not isinstance(raw, str) or not raw:
        raise BrokerError("path is required")
    p = Path(raw)
    if not p.is_absolute():
        raise BrokerError(f"path must be absolute: {raw!r}")
    # Traversal tokens are never accepted.
    if ".." in p.parts:
        raise BrokerError(f"path traversal rejected: {raw!r}")
    resolved = p.resolve(strict=False)
    if base is not None:
        base_resolved = base.resolve(strict=False)
        try:
            resolved.relative_to(base_resolved)
        except ValueError as exc:
            raise BrokerError(f"symlink/path escape outside {base}: {raw!r}") from exc
    return resolved


# --- State / manifests -----------------------------------------------------


def state_dir() -> Path:
    base = os.environ.get(
        "CMUX_HERMES_STATE_DIR",
        os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state")),
    )
    d = Path(base) / "cmux-hermes"
    if d.is_symlink():
        raise BrokerError(f"state dir must not be a symlink: {d}")
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except PermissionError as exc:
        raise BrokerError(f"cannot secure state dir {d}: {exc}") from exc
    return d


def tasks_dir() -> Path:
    d = state_dir() / "tasks"
    if d.is_symlink():
        raise BrokerError(f"tasks dir must not be a symlink: {d}")
    d.mkdir(parents=True, exist_ok=True)
    return d


def capabilities_dir() -> Path:
    d = state_dir() / "capabilities"
    if d.is_symlink():
        raise BrokerError(f"capabilities dir must not be a symlink: {d}")
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def _atomic_write_private(path: Path, payload: bytes, *, create_only: bool = False) -> None:
    """Write a 0600 file via a random O_EXCL temp and directory-relative rename."""
    parent = path.parent
    dir_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                     getattr(os, "O_NOFOLLOW", 0))
    tmp_name = f".tmp-{secrets.token_hex(12)}"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        if create_only:
            try:
                os.stat(path.name, dir_fd=dir_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise BrokerError(f"private state path already exists: {path}")
        fd = os.open(tmp_name, flags, 0o600, dir_fd=dir_fd)
        try:
            os.write(fd, payload)
            os.fsync(fd)
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        if create_only:
            # Reserve the destination atomically; hard-linking fails if it exists.
            os.link(tmp_name, path.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd,
                    follow_symlinks=False)
            os.unlink(tmp_name, dir_fd=dir_fd)
        else:
            os.rename(tmp_name, path.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except FileExistsError as exc:
        raise BrokerError(f"private state path already exists: {path}") from exc
    finally:
        try:
            os.unlink(tmp_name, dir_fd=dir_fd)
        except OSError:
            pass
        os.close(dir_fd)


def _read_private(path: Path) -> bytes:
    dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                     getattr(os, "O_NOFOLLOW", 0))
    try:
        fd = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise BrokerError(f"unsafe private state file: {path}")
            return os.read(fd, 1024 * 1024)
        finally:
            os.close(fd)
    finally:
        os.close(dir_fd)


def manifest_path(task_id: str) -> Path:
    if not SLUG_RE.match(task_id):
        raise BrokerError(f"unsafe task id: {task_id!r}")
    return tasks_dir() / f"{task_id}.json"


def load_manifest(task_id: str) -> dict[str, Any]:
    path = manifest_path(task_id)
    if not path.exists():
        raise BrokerError(f"no such task: {task_id!r}")
    return json.loads(_read_private(path).decode("utf-8"))


def save_manifest(task_id: str, data: dict[str, Any]) -> None:
    path = manifest_path(task_id)
    payload = (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write_private(path, payload)


def _capability_digest(capability: str) -> str:
    return hashlib.sha256(capability.encode("utf-8")).hexdigest()


def reserve_task(task_id: str, owner: str, capability: str) -> Path:
    """Atomically reserve a task id before creating any external resources."""
    path = manifest_path(task_id)
    lock_path = tasks_dir() / f"{task_id}.lock"
    if path.exists():
        raise BrokerError(f"task {task_id!r} already exists")
    payload = json.dumps({
        "task_id": task_id,
        "owner": owner,
        "owner_capability_sha256": _capability_digest(capability),
        "status": "reserving",
        "acquired_at": now_iso(),
    }, indent=2).encode("utf-8")
    try:
        _atomic_write_private(lock_path, payload, create_only=True)
    except BrokerError as exc:
        raise BrokerError(f"task {task_id!r} is already reserved") from exc
    return lock_path


def new_task_id() -> str:
    return f"task-{uuidlib.uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- cmux discovery --------------------------------------------------------


def cmux_ids() -> dict[str, str]:
    """Discover cmux surfaces with --id-format both. Returns long UUIDs only.

    Now derived from the structured workspace inventory rather than free-text
    parsing of ``tree``. Never serializes CMUX_* values.
    """
    surfaces: dict[str, str] = {}
    for ws in cmux_workspace_inventory():
        uuid = ws.get("workspace_uuid")
        if uuid:
            surfaces[uuid] = uuid
    return surfaces


def parse_cmux_inventory(raw: str) -> list[dict[str, Any]]:
    """Parse a structured cmux workspace-list JSON into normalized rows.

    Never executes cmux. Accepts both the live cmux schema (``id``,
    ``current_directory``, ``title``) and the normalized adapter schema. Every
    workspace must carry a full UUID and an absolute cwd; malformed rows block
    the inventory so callers cannot mistake an unreadable workspace for absence
    and create a duplicate. Treats all parsed text as untrusted.
    """
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BrokerError(f"cmux inventory is not valid JSON: {exc}") from exc
    if isinstance(obj, dict):
        rows = obj.get("workspaces")
        if not isinstance(rows, list):
            rows = obj.get("items")
        if not isinstance(rows, list):
            raise BrokerError("cmux inventory JSON has no workspace list")
    elif isinstance(obj, list):
        rows = obj
    else:
        raise BrokerError("cmux inventory JSON must be an object or list")
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise BrokerError("cmux inventory contains a non-object workspace")
        uuid = row.get("workspace_uuid") or row.get("uuid") or row.get("id")
        if not UUID_RE.match(str(uuid or "")):
            raise BrokerError("cmux inventory contains a workspace without a full UUID")
        cwd_raw = row.get("cwd") or row.get("current_directory")
        if not isinstance(cwd_raw, str) or not cwd_raw:
            raise BrokerError(
                f"cmux inventory workspace {uuid} has no absolute current directory"
            )
        try:
            cwd = safe_abs_path(cwd_raw)
        except BrokerError as exc:
            raise BrokerError(
                f"cmux inventory workspace {uuid} has invalid current directory: {exc}"
            ) from exc
        out.append({
            "workspace_uuid": str(uuid),
            "name": str(row.get("name") or row.get("title") or ""),
            "cwd": str(cwd),
        })
    return out


def cmux_workspace_inventory() -> list[dict[str, Any]]:
    """Structured cmux workspace inventory via argv-only JSON output.

    Replaces free-text ``tree`` parsing with structured JSON. Validates full
    UUIDs and absolute cwd for every row.
    """
    proc = run(
        [_bin("CMUX_BIN", "cmux"), "--id-format", "both", "--json",
         "list-workspaces"],
        timeout=20,
    )
    out = proc.stdout.decode("utf-8", "replace")
    return parse_cmux_inventory(out)


def assert_uuid(value: str, label: str) -> str:
    if not UUID_RE.match(value):
        raise BrokerError(f"unsafe {label}: {value!r} (must be a full UUID)")
    return value


# --- workspace reuse decision ---------------------------------------------


def _classify_cwd(cwd: str, project: Path) -> str:
    """Classify a workspace cwd vs a canonical project path."""
    try:
        c = Path(cwd).resolve(strict=False)
    except (OSError, ValueError):
        return "none"
    if c == project:
        return "exact"
    try:
        c.relative_to(project)
        return "inside-project"
    except ValueError:
        pass
    try:
        project.relative_to(c)
        return "broad-parent"
    except ValueError:
        return "none"


def resolve_cmux_workspace(project: Path, inventory: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Read-only reuse decision for a project. Never creates.

    Returns a structured result:
      decision: reuse | missing | ambiguous
      match_type: exact | inside-project | None
      selected: the single reusable workspace dict, or None
    Exact (cwd == project) wins. A single inside-project cwd is eligible.
    Broad-parent cwd is advisory only and never reused. Ties are ambiguous and
    fail closed.
    """
    project = project.resolve(strict=False)
    rows = inventory if inventory is not None else cmux_workspace_inventory()
    exact: list[dict[str, Any]] = []
    inside: list[dict[str, Any]] = []
    advisory: list[str] = []
    for ws in rows:
        kind = _classify_cwd(str(ws.get("cwd") or ""), project)
        if kind == "exact":
            exact.append(ws)
        elif kind == "inside-project":
            inside.append(ws)
        elif kind == "broad-parent":
            advisory.append(
                f"broad-parent workspace {ws.get('workspace_uuid')} cwd={ws.get('cwd')} "
                "is advisory only; not reused"
            )
    if len(exact) == 1:
        return {"decision": "reuse", "match_type": "exact",
                "selected": exact[0], "advisory": advisory}
    if len(exact) > 1:
        return {"decision": "ambiguous", "match_type": "exact",
                "selected": None, "advisory": advisory,
                "reason": "multiple exact (cwd==project) workspaces"}
    if len(inside) == 1:
        return {"decision": "reuse", "match_type": "inside-project",
                "selected": inside[0], "advisory": advisory}
    if len(inside) > 1:
        return {"decision": "ambiguous", "match_type": "inside-project",
                "selected": None, "advisory": advisory,
                "reason": "multiple inside-project workspaces"}
    return {"decision": "missing", "match_type": None,
            "selected": None, "advisory": advisory}


def ensure_cmux_workspace(cwd: Path, name: str) -> tuple[str, str]:
    """Reuse-or-create a non-focused cmux workspace for ``cwd``.

    Inventory before create, fail on ambiguity, re-inventory immediately before
    create (TOCTOU), create non-focused only when still missing, then validate
    the returned UUID and post-create identity. Returns (workspace_uuid, origin)
    where origin is 'reused' or 'created'. Only 'created' workspaces may later
    be closed by the owning task.
    """
    cwd = cwd.resolve(strict=False)
    # First inventory pass.
    inv = cmux_workspace_inventory()
    decision = resolve_cmux_workspace(cwd, inv)
    if decision["decision"] == "ambiguous":
        raise BrokerError(
            f"ambiguous workspace reuse for {cwd}: {decision.get('reason')}"
        )
    if decision["decision"] == "reuse":
        return decision["selected"]["workspace_uuid"], "reused"

    # TOCTOU: re-inventory immediately before create.
    inv2 = cmux_workspace_inventory()
    decision2 = resolve_cmux_workspace(cwd, inv2)
    if decision2["decision"] == "ambiguous":
        raise BrokerError(
            f"ambiguous workspace reuse (recheck) for {cwd}: {decision2.get('reason')}"
        )
    if decision2["decision"] == "reuse":
        return decision2["selected"]["workspace_uuid"], "reused"

    new_uuid = None
    try:
        cproc = run(
            [_bin("CMUX_BIN", "cmux"), "new-workspace", "--focus", "false",
             "--name", name, "--cwd", str(cwd)],
            timeout=20,
        )
        out = cproc.stdout.decode("utf-8", "replace")
        for tok in out.split():
            if UUID_RE.match(tok):
                new_uuid = tok
                break
        if not new_uuid:
            raise BrokerError("cmux new-workspace returned no full UUID")
        # Validate post-create identity: the UUID must now exist for this cwd.
        inv3 = cmux_workspace_inventory()
        found = next(
            (ws for ws in inv3
             if str(ws.get("workspace_uuid", "")).lower() == new_uuid.lower()),
            None,
        )
        if found is None:
            raise BrokerError(
                f"post-create identity check failed: {new_uuid} not in inventory"
            )
        found_cwd = found.get("cwd")
        if found_cwd and Path(found_cwd).resolve(strict=False) != cwd:
            raise BrokerError(
                f"post-create cwd mismatch: {found_cwd!r} != {cwd!r}"
            )
    except BaseException:
        # Creation can succeed before validation fails. Roll back only the UUID
        # returned by this create call; never close a pre-existing workspace.
        if new_uuid:
            try:
                run(
                    [_bin("CMUX_BIN", "cmux"), "close-workspace",
                     "--workspace", new_uuid],
                    timeout=20,
                )
            except BrokerError as cleanup_exc:
                sys.stderr.write(
                    f"warn: failed to close unvalidated workspace {new_uuid}: "
                    f"{cleanup_exc}\n"
                )
        raise
    return new_uuid, "created"


# --- Subcommand: doctor (token-free) ---------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    report: list[str] = []
    ok = True

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ok
        status = "ok" if cond else "FAIL"
        ok = ok and cond
        report.append(f"[{status}] {name}{(' - ' + detail) if detail else ''}")

    vinfo = (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
    py = ".".join(str(p) for p in vinfo)
    check("python", vinfo >= (3, 8), py)

    git = shutil.which(_bin("GIT_BIN", "git"))
    check("git", bool(git), git or "not found")

    cmux = shutil.which(_bin("CMUX_BIN", "cmux"))
    check("cmux binary", bool(cmux), cmux or "not found")

    if cmux:
        try:
            inv = cmux_workspace_inventory()
            check("cmux list-workspaces (structured json)", True,
                  f"{len(inv)} workspace(s)")
        except BrokerError as exc:
            check("cmux list-workspaces (structured json)", False, str(exc))
            ok = False

    tailscale = shutil.which(_bin("TAILSCALE_BIN", "tailscale"))
    check("tailscale binary", bool(tailscale), tailscale or "not found")
    if tailscale:
        try:
            proc = run([_bin("TAILSCALE_BIN", "tailscale"), "status"], timeout=15)
            up = proc.returncode == 0
            check("tailscale status", up)
        except BrokerError as exc:
            check("tailscale status", False, str(exc))

    target = args.target
    try:
        peer = assert_tailnet_target(target)
        check("ssh destination is an online Tailscale peer", True,
              f"{peer['effective_hostname']} -> {peer['peer']}")
        assert_remote_user(target)
        check(f"ssh {target} as {REMOTE_USER}", True)
    except BrokerError as exc:
        check("ssh destination is an online Tailscale peer", False, str(exc))
        check(f"ssh {target} as {REMOTE_USER}", False, str(exc))
        ok = False

    try:
        sd = state_dir()
        check("state dir writable", os.access(sd, os.W_OK), str(sd))
    except BrokerError as exc:
        check("state dir writable", False, str(exc))

    defaults = (
        f"defaults: concurrency={DEFAULT_CONCURRENCY} depth={DEFAULT_DEPTH} "
        f"delegation=disabled max_output={DEFAULT_MAX_OUTPUT} "
        f"max_turns={DEFAULT_MAX_TURNS} recursion=off"
    )
    report.append(defaults)

    sys.stdout.write("\n".join(report) + "\n")
    return 0 if ok else 1


# --- Subcommand: advisor (the only token-consuming op) ---------------------


def cmd_advisor(args: argparse.Namespace) -> int:
    if not args.yes:
        raise BrokerError(
            "advisor requires explicit opt-in: pass --yes to acknowledge a "
            "bounded, source=tool, safe/no-terminal model call"
        )
    raise BrokerError(
        "advisor is fail-closed: this Hermes CLI only accepts noninteractive "
        "queries through -q/argv, which can expose prompt text in process lists. "
        "Use the persistent Hermes master through a cmux SSH/tmux surface."
    )


# --- Subcommand: usage (recursive) -----------------------------------------


def _raw_usage(target: str, session_id: str | None = None) -> list[dict[str, Any]]:
    cmd = [HERMES_BIN, "sessions", "export", "-", "--format", "jsonl", "--redact"]
    if session_id:
        cmd += ["--session-id", session_id]
    proc = remote_run(target, cmd, timeout=30)
    rows: list[dict[str, Any]] = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def recursive_usage(target: str, session_id: str | None = None) -> dict[str, Any]:
    """Aggregate usage recursively by parent_session_id, grouped by provider/model."""
    rows = _raw_usage(target, session_id)
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        parent = str(row.get("parent_session_id", ""))
        by_parent.setdefault(parent, []).append(row)

    def descendants(pid: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for child in by_parent.get(pid, []):
            out.append(child)
            out.extend(descendants(str(child.get("session_id", ""))))
        return out

    if session_id:
        scope = [r for r in rows if str(r.get("session_id") or r.get("id") or "") == session_id]
        scope.extend(descendants(session_id))
    else:
        scope = rows

    grouped: dict[str, dict[str, Any]] = {}
    for row in scope:
        provider = row.get("billing_provider") or row.get("provider") or "?"
        key = f"{provider}/{row.get('model','?')}"
        g = grouped.setdefault(
            key, {"provider": provider, "model": row.get("model"),
                  "calls": 0, "tokens_in": 0, "tokens_out": 0, "rows": 0}
        )
        g["calls"] += int(row.get("api_call_count", 1) or 0)
        g["tokens_in"] += int(row.get("input_tokens", row.get("tokens_in", 0)) or 0)
        g["tokens_out"] += int(row.get("output_tokens", row.get("tokens_out", 0)) or 0)
        g["rows"] += 1

    return {"grouped": grouped, "scoped_rows": len(scope),
            "note": "Exact exported session rows; descendants require explicit child session IDs."}


def cmd_usage(args: argparse.Namespace) -> int:
    target = args.target
    assert_remote_user(target)
    result = recursive_usage(target, args.session)
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
    return 0


# --- Subcommand: persistent master -----------------------------------------


def cmd_master(args: argparse.Namespace) -> int:
    name = _validate_remote_token(args.name, SESSION_NAME_RE, "session name")
    target = args.target
    assert_remote_user(target)

    has = remote_run(target, ["tmux", "has-session", "-t", name], timeout=15)
    if has.returncode != 0:
        if args.attach_only:
            raise BrokerError(f"session {name!r} does not exist and --attach-only set")
        remote_run(
            target,
            ["tmux", "new-session", "-d", "-s", name, "-c", REMOTE_WORKDIR,
             HERMES_BIN, "chat", "--cli"],
            timeout=15,
        )
        action = "created"
    else:
        action = "reused"

    # Safety: never detach a parent that still has running children.
    if args.action == "detach":
        if _session_has_children(target, name):
            raise BrokerError(
                f"refusing to detach {name!r}: child processes still running"
            )
        remote_run(target, ["tmux", "detach-client", "-s", name], timeout=15)

    sys.stdout.write(
        json.dumps(
            {"session": name, "action": action, "target": target,
             "workdir": REMOTE_WORKDIR, "user": REMOTE_USER},
            indent=2,
        )
        + "\n"
    )
    return 0


def _session_has_children(target: str, name: str) -> bool:
    proc = remote_run(
        target,
        ["tmux", "list-panes", "-t", name, "-F", "#{pane_pid},#{pane_current_command}"],
        timeout=15,
    )
    out = proc.stdout.decode("utf-8", "replace")
    for line in out.splitlines():
        parts = line.split(",", 1)
        if len(parts) == 2 and parts[1].strip() not in ("", "0"):
            return True
    return False


# --- Subcommand: lane / worktree ownership ---------------------------------


def cmd_lane(args: argparse.Namespace) -> int:
    repo = safe_abs_path(args.repo)
    git = _bin("GIT_BIN", "git")

    def git_repo(args_list: list[str], **kw: Any) -> subprocess.CompletedProcess:
        return run([git, "-C", str(repo), *args_list], **kw)

    # Validate it is a git repo.
    if git_repo(["rev-parse", "--is-inside-work-tree"]).returncode != 0:
        raise BrokerError(f"not a git work tree: {repo}")

    base = args.base
    if git_repo(["rev-parse", "--verify", base]).returncode != 0:
        raise BrokerError(f"base branch not found: {base!r}")

    slug = _validate_remote_token(args.slug, SLUG_RE, "slug")
    branch = f"cmux-hermes/{slug}"
    wt_root = repo / ".cmux-hermes-worktrees"
    wt = wt_root / slug

    if wt_root.is_symlink():
        raise BrokerError(f"worktree root must not be a symlink: {wt_root}")
    safe_abs_path(str(wt), base=repo)

    if wt.exists() or wt.is_symlink():
        raise BrokerError(f"worktree path already exists (never auto-overwrite): {wt}")

    owner = os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown"
    task_id = args.task_id or new_task_id()
    # Validate and check the task id before any worktree or cmux mutation.
    manifest_path(task_id)

    plan = {
        "task_id": task_id,
        "repo": str(repo),
        "base": base,
        "slug": slug,
        "branch": branch,
        "worktree": str(wt),
        "owner": owner,
        "cmux_workspace_uuid": None,
        "status": "planned",
        "created_at": now_iso(),
    }

    if args.dry_run:
        plan["status"] = "dry-run"
        sys.stdout.write(json.dumps({"dry_run": plan}, indent=2) + "\n")
        return 0

    capability = secrets.token_urlsafe(32)
    lock_path = reserve_task(task_id, owner, capability)
    capability_path = capabilities_dir() / f"cap-{secrets.token_hex(16)}"
    wt_created = False
    ws_uuid = None
    ws_origin = None
    try:
        _atomic_write_private(capability_path, (capability + "\n").encode("utf-8"),
                              create_only=True)
        wt_root.mkdir(parents=True, exist_ok=True)
        # One worktree, one branch, one capability-held owner lock.
        proc = git_repo(["worktree", "add", "-b", branch, str(wt), base])
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
            raise BrokerError("git worktree add failed; worktree not created")
        wt_created = True

        # Reuse-or-create the cmux workspace for this worktree. Reuse only an
        # exact existing workspace for this worktree; never reuse an existing
        # task/worktree without its owner capability.
        ws_uuid, ws_origin = ensure_cmux_workspace(
            wt, f"cmux-hermes-{slug}"
        )
        plan["cmux_workspace_uuid"] = ws_uuid
        plan["workspace_origin"] = ws_origin
        plan["created_workspace"] = ws_origin == "created"
        plan["status"] = "active"
        save_manifest(task_id, plan)
        lock = {
            "task_id": task_id,
            "owner": owner,
            "owner_capability_sha256": _capability_digest(capability),
            "worktree": str(wt),
            "status": "active",
            "created_workspace": ws_origin == "created",
            "acquired_at": now_iso(),
        }
        _atomic_write_private(
            lock_path, (json.dumps(lock, indent=2) + "\n").encode("utf-8")
        )
    except BaseException:
        # Only close a workspace this task actually created; a reused workspace
        # must survive any failure of this task.
        if ws_uuid and ws_origin == "created":
            run(
                [_bin("CMUX_BIN", "cmux"), "close-workspace", "--workspace", ws_uuid],
                timeout=20,
            )
        if wt_created:
            git_repo(["worktree", "remove", "--force", str(wt)])
            git_repo(["branch", "-D", branch])
        try:
            manifest_path(task_id).unlink(missing_ok=True)
            lock_path.unlink(missing_ok=True)
            capability_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    output = dict(plan)
    output["owner_capability_file"] = str(capability_path)
    output["owner_capability_note"] = (
        "This 0600 file is required for cancel, close, and cleanup. Its secret is never printed or placed in argv."
    )
    sys.stdout.write(json.dumps(output, indent=2) + "\n")
    return 0


def _load_owner_capability(raw_path: str) -> str:
    path = safe_abs_path(raw_path, base=capabilities_dir())
    value = _read_private(path).decode("utf-8").strip()
    if len(value) < 32:
        raise BrokerError("invalid owner capability file")
    return value


def _enforce_single_owner(task_id: str, capability_file: str) -> dict[str, Any]:
    lock_path = tasks_dir() / f"{task_id}.lock"
    if not lock_path.exists():
        raise BrokerError(f"no owner lock for task {task_id!r}; refusing mutation")
    lock = json.loads(_read_private(lock_path).decode("utf-8"))
    capability = _load_owner_capability(capability_file)
    expected = str(lock.get("owner_capability_sha256") or "")
    if not expected or not hmac.compare_digest(expected, _capability_digest(capability)):
        raise BrokerError(f"invalid owner capability for task {task_id!r}")
    return lock


# --- Subcommand: send ------------------------------------------------------


def cmd_send(args: argparse.Namespace) -> int:
    workspace = assert_uuid(args.workspace, "workspace UUID")
    surface = assert_uuid(args.surface, "surface UUID")
    message = args.message if args.message is not None else sys.stdin.read()
    if not message.strip():
        raise BrokerError("empty message")
    # Bound screen output; screen text is untrusted.
    cmd = [_bin("CMUX_BIN", "cmux"), "send", "--workspace", workspace,
           "--surface", surface, "--", message]
    proc = run(cmd, timeout=args.timeout)
    out = (proc.stdout or b"").decode("utf-8", "replace")
    bounded = out[: DEFAULT_MAX_OUTPUT * 4]
    sys.stdout.write(bounded)
    return proc.returncode


def _task_created_workspace(plan: dict[str, Any]) -> bool:
    """True only if this task created (not reused) its cmux workspace."""
    if plan.get("workspace_origin"):
        return plan.get("workspace_origin") == "created"
    # Backward-compatible default for manifests predating workspace_origin.
    return bool(plan.get("created_workspace"))


def _maybe_close_created_workspace(plan: dict[str, Any]) -> None:
    """Close a workspace only if this task created it. Reused ones survive."""
    if not plan.get("cmux_workspace_uuid"):
        return
    if not _task_created_workspace(plan):
        return
    try:
        run(
            [_bin("CMUX_BIN", "cmux"), "close-workspace",
             "--workspace", plan["cmux_workspace_uuid"]],
            timeout=20,
        )
    except BrokerError as exc:
        sys.stderr.write(f"warn: cmux close failed: {exc}\n")


# --- Subcommand: cancel / close (no branch/worktree deletion) --------------


def cmd_cancel(args: argparse.Namespace) -> int:
    task_id = args.task
    plan = load_manifest(task_id)
    _enforce_single_owner(task_id, args.owner_capability_file)
    # Stop/close sessions; never delete branches or worktrees. Only a workspace
    # this task created is closed; a reused workspace is preserved.
    _maybe_close_created_workspace(plan)
    plan["status"] = "cancelled"
    plan["cancelled_at"] = now_iso()
    save_manifest(task_id, plan)
    note = ("branches and worktrees preserved"
            + ("; reused workspace preserved"
               if plan.get("cmux_workspace_uuid")
               and not _task_created_workspace(plan) else ""))
    sys.stdout.write(json.dumps({"task_id": task_id, "status": "cancelled",
                                 "note": note}, indent=2) + "\n")
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    task_id = args.task
    plan = load_manifest(task_id)
    _enforce_single_owner(task_id, args.owner_capability_file)
    # Close only a workspace this task created; preserve a reused one.
    _maybe_close_created_workspace(plan)
    plan["status"] = "closed"
    plan["closed_at"] = now_iso()
    save_manifest(task_id, plan)
    note = ("branches and worktrees preserved"
            + ("; reused workspace preserved"
               if plan.get("cmux_workspace_uuid")
               and not _task_created_workspace(plan) else ""))
    sys.stdout.write(json.dumps({"task_id": task_id, "status": "closed",
                                 "note": note}, indent=2) + "\n")
    return 0


# --- Subcommand: cleanup (report-only by default) --------------------------


def cmd_cleanup(args: argparse.Namespace) -> int:
    task_id = args.task
    plan = load_manifest(task_id)
    _enforce_single_owner(task_id, args.owner_capability_file)
    if plan.get("status") not in {"closed", "cancelled"}:
        raise BrokerError("cleanup requires a closed or cancelled task")
    repo = Path(plan["repo"])
    wt = Path(plan["worktree"])
    git = _bin("GIT_BIN", "git")

    def git_repo(argv: list[str]) -> subprocess.CompletedProcess:
        return run([git, "-C", str(repo), *argv], timeout=30)

    report: dict[str, Any] = {"task_id": task_id, "force": bool(args.force), "checks": {}}

    clean = False
    merged = False
    if wt.exists():
        dirty = run([git, "-C", str(wt), "status", "--porcelain"], timeout=30)
        out = dirty.stdout.decode("utf-8", "replace").strip() if dirty.stdout else ""
        clean = dirty.returncode == 0 and out == ""
        merged_proc = git_repo([
            "for-each-ref", "--merged", plan.get("base", "main"),
            "--format=%(refname:short)", "refs/heads/",
        ])
        merged_names = {
            line.strip() for line in merged_proc.stdout.decode("utf-8", "replace").splitlines()
            if line.strip()
        }
        merged = merged_proc.returncode == 0 and plan.get("branch") in merged_names
    else:
        clean = merged = False
    report["checks"]["worktree_clean"] = clean
    report["checks"]["branch_merged"] = merged

    if not args.force:
        report["action"] = "report-only"
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
        return 0

    if not (clean and merged):
        raise BrokerError(
            "destructive cleanup refused: worktree not clean or branch not merged "
            "(safety proof unreliable); leaving worktree and branch intact"
        )
    # Only now: remove worktree entry and branch.
    removed = git_repo(["worktree", "remove", str(wt)])
    if removed.returncode != 0:
        raise BrokerError("git worktree removal failed; branch preserved")
    deleted = git_repo(["branch", "-D", plan["branch"]])
    if deleted.returncode != 0:
        raise BrokerError("worktree removed but merged branch deletion failed")
    report["action"] = "removed"
    sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0


# --- Subcommand: list/show tasks -------------------------------------------


def cmd_tasks(args: argparse.Namespace) -> int:
    out: list[dict[str, Any]] = []
    for f in sorted(tasks_dir().glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    if args.task:
        sys.stdout.write(json.dumps(load_manifest(args.task), indent=2) + "\n")
        return 0
    sys.stdout.write(json.dumps(out, indent=2) + "\n")
    return 0


# --- Subcommand: resolve / workspace (reuse-first) ------------------------


def cmd_resolve(args: argparse.Namespace) -> int:
    """Read-only reuse decision for a project. Never creates, never sends."""
    project = safe_abs_path(args.project)
    result = resolve_cmux_workspace(project)
    sys.stdout.write(
        json.dumps({"project": str(project), **result}, indent=2) + "\n"
    )
    return 0 if result["decision"] in ("reuse", "missing") else 2


def cmd_workspace(args: argparse.Namespace) -> int:
    """Reuse-or-create a non-focused cmux workspace for a cwd."""
    if args.action == "resolve":
        return cmd_resolve(args)
    cwd = safe_abs_path(args.cwd)
    name = _validate_remote_token(args.name, SESSION_NAME_RE, "workspace name")
    ws_uuid, origin = ensure_cmux_workspace(cwd, name)
    sys.stdout.write(
        json.dumps({"workspace_uuid": ws_uuid, "origin": origin,
                    "cwd": str(cwd), "name": name}, indent=2) + "\n"
    )
    return 0


# --- argparse plumbing -----------------------------------------------------


def _add_target(p: argparse.ArgumentParser) -> None:
    p.add_argument("--target", default=DEFAULT_TARGET,
                   help=f"ssh target alias (default: {DEFAULT_TARGET})")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cmux-hermes",
        description="Deterministic cmux + Hermes orchestration broker (safe boundary).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="token-free environment health check")
    _add_target(d)
    d.set_defaults(func=cmd_doctor)

    a = sub.add_parser("advisor", help="bounded, opt-in advisor model query")
    _add_target(a)
    a.add_argument("--yes", action="store_true",
                   help="explicit opt-in: acknowledge a bounded safe model call")
    a.add_argument("--model", required=True, help="model id (validated)")
    a.add_argument("--provider", default=None, help="provider id (validated)")
    a.add_argument("--toolset", default="safe",
                   choices=["safe", "no-terminal", "none"])
    a.add_argument("--max-output", type=int, default=DEFAULT_MAX_OUTPUT)
    a.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    a.add_argument("--max-prompt-bytes", type=int, default=DEFAULT_MAX_PROMPT_BYTES)
    a.add_argument("--prompt-file", default=None,
                   help="read prompt from this absolute path; else stdin")
    a.add_argument("--timeout", type=int, default=180)
    a.set_defaults(func=cmd_advisor, action="query")

    u = sub.add_parser("usage", help="exact session usage grouped by provider/model")
    _add_target(u)
    u.add_argument("--session", required=True, help="exact session id to export and aggregate")
    u.set_defaults(func=cmd_usage)

    m = sub.add_parser("master", help="persistent Hermes master in a remote tmux session")
    _add_target(m)
    m.add_argument("action", choices=["ensure", "attach", "detach"])
    m.add_argument("--name", required=True)
    m.add_argument("--attach-only", action="store_true",
                   help="never create; fail if absent")
    m.set_defaults(func=cmd_master)

    l = sub.add_parser("lane", help="create a write-isolated worktree + cmux workspace")
    l.add_argument("repo", help="absolute path to the git repo")
    l.add_argument("--base", required=True, help="base branch to branch from")
    l.add_argument("--slug", required=True, help="lane slug [a-z0-9-]")
    l.add_argument("--task-id", default=None)
    l.add_argument("--dry-run", action="store_true")
    l.set_defaults(func=cmd_lane)

    s = sub.add_parser("send", help="send to an explicit workspace/surface UUID")
    s.add_argument("--workspace", required=True)
    s.add_argument("--surface", required=True)
    s.add_argument("--message", default=None, help="message text; else stdin")
    s.add_argument("--max-output", type=int, default=DEFAULT_MAX_OUTPUT)
    s.add_argument("--timeout", type=int, default=60)
    s.set_defaults(func=cmd_send)

    c = sub.add_parser("cancel", help="stop/close sessions; never delete branches/worktrees")
    c.add_argument("--task", required=True)
    c.add_argument("--owner-capability-file", required=True,
                   help="0600 capability file returned by lane creation")
    c.set_defaults(func=cmd_cancel)

    cl = sub.add_parser("close", help="close a task; preserve branches/worktrees")
    cl.add_argument("--task", required=True)
    cl.add_argument("--owner-capability-file", required=True,
                    help="0600 capability file returned by lane creation")
    cl.set_defaults(func=cmd_close)

    cu = sub.add_parser("cleanup", help="report-only by default; --force needs clean+merged proof")
    cu.add_argument("--task", required=True)
    cu.add_argument("--owner-capability-file", required=True,
                    help="0600 capability file returned by lane creation")
    cu.add_argument("--force", action="store_true")
    cu.set_defaults(func=cmd_cleanup)

    t = sub.add_parser("tasks", help="list or show task manifests")
    t.add_argument("--task", default=None)
    t.set_defaults(func=cmd_tasks)

    rs = sub.add_parser("resolve", help="read-only reuse decision for a project")
    rs.add_argument("project", help="absolute path to the project/worktree")
    rs.set_defaults(func=cmd_resolve)

    ws = sub.add_parser("workspace", help="reuse-or-create a cmux workspace")
    ws.add_argument("action", choices=["ensure", "resolve"],
                    help="ensure = reuse-or-create; resolve = read-only")
    ws.add_argument("--cwd", default=None,
                    help="absolute worktree cwd (ensure)")
    ws.add_argument("--name", default="cmux-hermes",
                    help="workspace name (ensure)")
    ws.add_argument("--project", default=None,
                    help="absolute project path (resolve)")
    ws.set_defaults(func=cmd_workspace)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except BrokerError as exc:
        sys.stderr.write(f"blocked: {exc}\n")
        return 2
    except KeyboardInterrupt:
        sys.stderr.write("interrupted\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())
