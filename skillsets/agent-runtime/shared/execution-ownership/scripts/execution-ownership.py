#!/usr/bin/env python3
"""Fail-closed host-local single-flight execution leases."""
from __future__ import annotations

import argparse
import errno
import fcntl
import hashlib
import json
import math
import os
import re
import secrets
import socket
import stat
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1
DIR_MODE = 0o700
FILE_MODE = 0o600
DEFAULT_STALE_AFTER = 900.0
OWNER_ID_RE = re.compile(r"^[0-9a-f]{32}$")
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")

EXIT_OK = 0
EXIT_MALFORMED_TARGET = 2
EXIT_MISSING = 13
EXIT_NOT_OWNER = 12
EXIT_HELD = 10
EXIT_STALE = 11
EXIT_ERROR = 14


class LeaseError(Exception):
    """A recoverable, fail-closed lease error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class TargetError(LeaseError):
    def __init__(self, message: str):
        super().__init__("malformed_target", message)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _host_name() -> str:
    return socket.gethostname() or "unknown-host"


def _default_root() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else Path.home() / ".local" / "state"
    return base / "ai-config-kit" / "execution-ownership"


def _validate_text(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise TargetError(f"{name} must be a non-empty string of at most {maximum} characters")
    if value != value.strip() or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise TargetError(f"{name} contains surrounding whitespace or control characters")
    return value


def _canonical_directory(value: Any, name: str) -> str:
    raw = _validate_text(value, name, 4096)
    path = Path(raw)
    if not path.is_absolute():
        raise TargetError(f"{name} must be an absolute path")
    try:
        if path.is_symlink():
            raise TargetError(f"{name} must not be a symlink")
        info = os.lstat(path)
    except FileNotFoundError as exc:
        raise TargetError(f"{name} must exist") from exc
    except OSError as exc:
        raise TargetError(f"cannot inspect {name}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode):
        raise TargetError(f"{name} must not be a symlink")
    if not stat.S_ISDIR(info.st_mode):
        raise TargetError(f"{name} must be a directory")
    return os.path.normcase(os.path.realpath(path))


@dataclass(frozen=True)
class Target:
    repo: str
    worktree: str
    branch: str
    commit: str
    operation: str

    def as_dict(self) -> dict[str, str]:
        return {
            "repo": self.repo,
            "worktree": self.worktree,
            "branch": self.branch,
            "commit": self.commit,
            "operation": self.operation,
        }

    @property
    def canonical_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @property
    def key(self) -> str:
        digest = hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"


def canonical_target(repo: Any, worktree: Any, branch: Any, commit: Any, operation: Any) -> Target:
    """Validate and canonicalize a target before any lease filesystem access."""
    commit_value = _validate_text(commit, "commit", 64)
    if not COMMIT_RE.fullmatch(commit_value):
        raise TargetError("commit must be 7-64 hexadecimal characters")
    return Target(
        repo=_canonical_directory(repo, "repo"),
        worktree=_canonical_directory(worktree, "worktree"),
        branch=_validate_text(branch, "branch", 256),
        commit=commit_value.lower(),
        operation=_validate_text(operation, "operation", 128),
    )


def _secure_root(root: Path) -> Path:
    if not root.is_absolute():
        raise LeaseError("unsafe_root", "lease root must be an absolute path")
    try:
        if root.is_symlink():
            raise LeaseError("unsafe_root", "lease root must not be a symlink")
        root.mkdir(parents=True, exist_ok=True)
        info = os.lstat(root)
    except LeaseError:
        raise
    except OSError as exc:
        raise LeaseError("root_error", f"cannot create lease root: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise LeaseError("unsafe_root", "lease root must be a regular directory")
    try:
        os.chmod(root, DIR_MODE)
    except OSError as exc:
        raise LeaseError("root_error", f"cannot tighten lease root permissions: {exc}") from exc
    return root


def _pid_alive(pid: int) -> bool | None:
    """Return true/false, or None when liveness is ambiguous."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        return None
    return True


class LeaseStore:
    """Filesystem-backed leases with one serialized state transition."""

    def __init__(self, root: Path | str | None = None, *, stale_after: float = DEFAULT_STALE_AFTER,
                 clock: Any = time.time, host: Any = _host_name, pid_alive: Any = _pid_alive,
                 bb_thread_id: str | None = None):
        if not isinstance(stale_after, (int, float)) or isinstance(stale_after, bool):
            raise LeaseError("invalid_stale_after", "stale-after must be numeric")
        if not math.isfinite(float(stale_after)) or stale_after <= 0:
            raise LeaseError("invalid_stale_after", "stale-after must be finite and greater than zero")
        self.root = Path(root) if root is not None else _default_root()
        self.stale_after = float(stale_after)
        self.clock = clock
        self.host = host
        self.pid_alive = pid_alive
        owner_thread = bb_thread_id if bb_thread_id is not None else os.environ.get("BB_THREAD_ID")
        owner_thread = owner_thread or None
        if owner_thread is not None:
            try:
                self.owner_thread = _validate_text(owner_thread, "owner_thread", 128)
            except TargetError as exc:
                raise LeaseError("invalid_owner_metadata", exc.message) from exc
        else:
            self.owner_thread = None

    def lease_path(self, target: Target) -> Path:
        return self.root / self._filename(target)

    @staticmethod
    def _filename(target: Target) -> str:
        return f"lease-{target.key.removeprefix('sha256:')}.json"

    @contextmanager
    def _locked_root(self) -> Iterator[int]:
        root = _secure_root(self.root)
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            root_fd = os.open(root, flags)
        except OSError as exc:
            raise LeaseError("root_error", f"cannot safely open lease root: {exc}") from exc
        try:
            if not stat.S_ISDIR(os.fstat(root_fd).st_mode):
                raise LeaseError("unsafe_root", "lease root is not a directory")
            lock_flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            try:
                lock_fd = os.open(".lock", lock_flags, FILE_MODE, dir_fd=root_fd)
            except OSError as exc:
                raise LeaseError("lock_error", f"cannot safely open lease lock: {exc}") from exc
            try:
                if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
                    raise LeaseError("unsafe_lock", "lease lock is not a regular file")
                os.fchmod(lock_fd, FILE_MODE)
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                yield root_fd
            finally:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                finally:
                    os.close(lock_fd)
        finally:
            os.close(root_fd)

    def _load(self, root_fd: int, target: Target) -> dict[str, Any] | None:
        filename = self._filename(target)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(filename, flags, dir_fd=root_fd)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise LeaseError("state_error", f"cannot safely open lease state: {exc}") from exc
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise LeaseError("state_error", "lease state is not a regular file")
            os.fchmod(fd, FILE_MODE)
            with os.fdopen(fd, "r", encoding="utf-8") as handle:
                try:
                    state = json.load(handle)
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise LeaseError("malformed_lease", f"lease state is not valid JSON: {exc}") from exc
        except LeaseError:
            raise
        except OSError as exc:
            raise LeaseError("state_error", f"cannot read lease state: {exc}") from exc
        self._validate_state(state, target)
        return state

    def _validate_state(self, state: Any, target: Target) -> None:
        if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
            raise LeaseError("malformed_lease", "unsupported or missing lease schema")
        if state.get("target_key") != target.key or state.get("target") != target.as_dict():
            raise LeaseError("ambiguous_target", "lease state does not match its canonical target key")
        owner = state.get("owner")
        if not isinstance(owner, dict):
            raise LeaseError("malformed_lease", "lease owner metadata is missing")
        owner_id = owner.get("owner_id")
        if not isinstance(owner_id, str) or not OWNER_ID_RE.fullmatch(owner_id):
            raise LeaseError("malformed_lease", "lease owner id is invalid")
        pid = owner.get("pid")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise LeaseError("malformed_lease", "lease owner pid is invalid")
        pgid = owner.get("pgid")
        if isinstance(pgid, bool) or not isinstance(pgid, int) or pgid <= 0:
            raise LeaseError("malformed_lease", "lease owner process group is invalid")
        host = owner.get("host")
        if not isinstance(host, str) or not host or any(ord(char) < 0x20 for char in host):
            raise LeaseError("malformed_lease", "lease owner host is invalid")
        heartbeat_unix = owner.get("heartbeat_unix")
        if isinstance(heartbeat_unix, bool) or not isinstance(heartbeat_unix, (int, float)):
            raise LeaseError("malformed_lease", "lease heartbeat time is invalid")
        if not math.isfinite(float(heartbeat_unix)) or heartbeat_unix < 0:
            raise LeaseError("malformed_lease", "lease heartbeat time is invalid")
        if "owner_thread" in owner:
            try:
                _validate_text(owner["owner_thread"], "owner_thread", 128)
            except TargetError as exc:
                raise LeaseError("malformed_lease", exc.message) from exc
        for field in ("acquired_at", "heartbeat_at"):
            if not isinstance(owner.get(field), str) or not owner[field]:
                raise LeaseError("malformed_lease", f"lease owner field {field} is missing")

    def _write(self, root_fd: int, target: Target, state: dict[str, Any]) -> None:
        filename = self._filename(target)
        temp_name = f".lease-{secrets.token_hex(12)}.tmp"
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(temp_name, flags, FILE_MODE, dir_fd=root_fd)
        except OSError as exc:
            raise LeaseError("state_error", f"cannot create atomic lease state: {exc}") from exc
        try:
            encoded = (json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")
            os.write(fd, encoded)
            os.fsync(fd)
            os.fchmod(fd, FILE_MODE)
            os.close(fd)
            fd = -1
            os.replace(temp_name, filename, src_dir_fd=root_fd, dst_dir_fd=root_fd)
        except OSError as exc:
            raise LeaseError("state_error", f"cannot atomically write lease state: {exc}") from exc
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(temp_name, dir_fd=root_fd)
            except FileNotFoundError:
                pass
            except OSError:
                pass

    def _new_state(self, target: Target) -> tuple[dict[str, Any], str]:
        now = float(self.clock())
        iso = _utc_now()
        token = secrets.token_hex(16)
        pgid = os.getpgid(os.getpid())
        owner = {
            "owner_id": token,
            "pid": os.getpid(),
            "pgid": pgid,
            "host": str(self.host()),
            "acquired_at": iso,
            "heartbeat_at": iso,
            "heartbeat_unix": now,
        }
        if self.owner_thread is not None:
            owner["owner_thread"] = self.owner_thread
        return {
            "schema_version": SCHEMA_VERSION,
            "target": target.as_dict(),
            "target_key": target.key,
            "owner": owner,
        }, token

    def _create(self, root_fd: int, target: Target) -> tuple[dict[str, Any], str]:
        state, token = self._new_state(target)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self._filename(target), flags, FILE_MODE, dir_fd=root_fd)
        except FileExistsError:
            raise
        except OSError as exc:
            raise LeaseError("state_error", f"cannot create lease state: {exc}") from exc
        try:
            encoded = (json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")
            os.write(fd, encoded)
            os.fsync(fd)
            os.fchmod(fd, FILE_MODE)
        except OSError as exc:
            raise LeaseError("state_error", f"cannot initialize lease state: {exc}") from exc
        finally:
            os.close(fd)
        return state, token

    def _age(self, state: dict[str, Any]) -> float:
        age = float(self.clock()) - float(state["owner"]["heartbeat_unix"])
        if age < 0:
            raise LeaseError("clock_ambiguous", "lease heartbeat is in the future")
        return age

    def _status_for_existing(self, state: dict[str, Any], target: Target) -> dict[str, Any]:
        owner = state["owner"]
        age = self._age(state)
        if age < self.stale_after:
            return {
                "status": "held", "code": "held", "target_key": target.key,
                "age_seconds": round(age, 6),
                "owner": {"pid": owner["pid"], "pgid": owner["pgid"], "host": owner["host"], "heartbeat_at": owner["heartbeat_at"]},
            }
        if owner["host"] != str(self.host()):
            raise LeaseError("ambiguous_owner", "stale lease belongs to another host")
        alive = self.pid_alive(owner["pid"])
        if alive is None:
            raise LeaseError("ambiguous_owner", "cannot determine whether stale lease owner is alive")
        try:
            current_pgid = os.getpgid(owner["pid"]) if alive else None
        except ProcessLookupError:
            current_pgid = None
            alive = False
        except OSError as exc:
            raise LeaseError("ambiguous_owner", f"cannot determine stale owner process group: {exc}") from exc
        if alive and current_pgid != owner["pgid"]:
            raise LeaseError("ambiguous_owner", "stale owner pid was reused by another process group")
        if alive:
            return {
                "status": "stale", "code": "stale_owner_alive", "target_key": target.key,
                "age_seconds": round(age, 6),
                "owner": {"pid": owner["pid"], "pgid": owner["pgid"], "host": owner["host"], "heartbeat_at": owner["heartbeat_at"]},
            }
        return {"status": "reclaimable", "code": "stale_owner_gone", "target_key": target.key}

    def acquire(self, target: Target) -> dict[str, Any]:
        with self._locked_root() as root_fd:
            existing = self._load(root_fd, target)
            reclaimed = False
            if existing is not None:
                current = self._status_for_existing(existing, target)
                if current["status"] != "reclaimable":
                    return current
                try:
                    os.unlink(self._filename(target), dir_fd=root_fd)
                except OSError as exc:
                    raise LeaseError("state_error", f"cannot reclaim stale lease: {exc}") from exc
                reclaimed = True
            try:
                state, token = self._create(root_fd, target)
            except FileExistsError as exc:
                raise LeaseError("ambiguous_acquire", "lease appeared during acquire") from exc
            return {
                "status": "reclaimed" if reclaimed else "acquired",
                "code": "reclaimed" if reclaimed else "acquired",
                "target_key": target.key,
                "owner_id": token,
                "owner": state["owner"],
            }

    def heartbeat(self, target: Target, owner_id: str) -> dict[str, Any]:
        if not isinstance(owner_id, str) or not OWNER_ID_RE.fullmatch(owner_id):
            return {"status": "not_owner", "code": "invalid_owner_id", "target_key": target.key}
        with self._locked_root() as root_fd:
            state = self._load(root_fd, target)
            if state is None:
                return {"status": "missing", "code": "missing", "target_key": target.key}
            owner = state["owner"]
            if owner["owner_id"] != owner_id:
                return {"status": "not_owner", "code": "not_owner", "target_key": target.key}
            if owner["host"] != str(self.host()):
                raise LeaseError("ambiguous_owner", "lease owner belongs to another host")
            owner["heartbeat_unix"] = float(self.clock())
            owner["heartbeat_at"] = _utc_now()
            self._write(root_fd, target, state)
            return {"status": "renewed", "code": "renewed", "target_key": target.key,
                    "owner_id": owner_id, "heartbeat_at": owner["heartbeat_at"]}

    def release(self, target: Target, owner_id: str) -> dict[str, Any]:
        if not isinstance(owner_id, str) or not OWNER_ID_RE.fullmatch(owner_id):
            return {"status": "not_owner", "code": "invalid_owner_id", "target_key": target.key}
        with self._locked_root() as root_fd:
            state = self._load(root_fd, target)
            if state is None:
                return {"status": "missing", "code": "missing", "target_key": target.key}
            if state["owner"]["owner_id"] != owner_id:
                return {"status": "not_owner", "code": "not_owner", "target_key": target.key}
            if state["owner"]["host"] != str(self.host()):
                raise LeaseError("ambiguous_owner", "lease owner belongs to another host")
            try:
                os.unlink(self._filename(target), dir_fd=root_fd)
            except OSError as exc:
                raise LeaseError("state_error", f"cannot release lease: {exc}") from exc
            return {"status": "released", "code": "released", "target_key": target.key}

    def inspect(self, target: Target) -> dict[str, Any]:
        with self._locked_root() as root_fd:
            state = self._load(root_fd, target)
            if state is None:
                return {"status": "missing", "code": "missing", "target_key": target.key}
            result = self._status_for_existing(state, target)
            if result["status"] == "reclaimable":
                return {"status": "stale", "code": "stale_owner_gone", "target_key": target.key, "reclaimable": True}
            return result


def _target_from_args(args: argparse.Namespace) -> Target:
    return canonical_target(args.repo, args.worktree, args.branch, args.commit, args.operation)


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--stale-after", type=float, default=DEFAULT_STALE_AFTER)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--bb-thread-id", default=None,
                        help="optional BB thread owner identifier; omitted outside BB")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("acquire")
    heartbeat = commands.add_parser("heartbeat")
    heartbeat.add_argument("--owner-id", required=True)
    release = commands.add_parser("release")
    release.add_argument("--owner-id", required=True)
    commands.add_parser("inspect")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        target = _target_from_args(args)
        store = LeaseStore(args.root, stale_after=args.stale_after, bb_thread_id=args.bb_thread_id)
        if args.command == "acquire":
            result = store.acquire(target)
        elif args.command == "heartbeat":
            result = store.heartbeat(target, args.owner_id)
        elif args.command == "release":
            result = store.release(target, args.owner_id)
        else:
            result = store.inspect(target)
        _emit(result)
        return {"acquired": EXIT_OK, "reclaimed": EXIT_OK, "renewed": EXIT_OK,
                "released": EXIT_OK, "held": EXIT_HELD, "stale": EXIT_STALE,
                "missing": EXIT_MISSING, "not_owner": EXIT_NOT_OWNER}.get(
                    result.get("status"), EXIT_ERROR)
    except TargetError as exc:
        _emit({"status": "error", "code": exc.code, "message": exc.message})
        return EXIT_MALFORMED_TARGET
    except LeaseError as exc:
        _emit({"status": "error", "code": exc.code, "message": exc.message})
        return EXIT_ERROR
    except (OSError, ValueError, TypeError) as exc:
        _emit({"status": "error", "code": "error", "message": str(exc)})
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
