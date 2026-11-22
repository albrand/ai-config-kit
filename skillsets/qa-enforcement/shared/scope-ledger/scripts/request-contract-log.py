#!/usr/bin/env python3
"""Append request-contract metadata without recording contract text."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys


THREAD_ID = re.compile(r"thr_[A-Za-z0-9]+\Z")
ROOT_FIELDS = {"target", "outcomes", "constraints", "state_claims"}
OUTCOME_FIELDS = {"request", "status", "evidence", "blocker"}
STATUSES = ("complete", "blocked")


class ContractError(Exception):
    pass


def _nonempty_string(value):
    return isinstance(value, str) and bool(value.strip())


def _validate_contract(contract):
    if not isinstance(contract, dict) or set(contract) != ROOT_FIELDS:
        raise ContractError("contract must contain target, outcomes, constraints, and state_claims")
    if not _nonempty_string(contract["target"]):
        raise ContractError("target must be a non-empty string")
    if not isinstance(contract["outcomes"], list) or not contract["outcomes"]:
        raise ContractError("outcomes must be a non-empty list")
    for index, row in enumerate(contract["outcomes"], start=1):
        if not isinstance(row, dict) or set(row) != OUTCOME_FIELDS:
            raise ContractError(f"outcome row {index} must contain request, status, evidence, and blocker")
        if not _nonempty_string(row["request"]):
            raise ContractError(f"outcome row {index} request must be a non-empty string")
        if row["status"] not in STATUSES:
            raise ContractError(f"outcome row {index} status must be complete or blocked")
        if row["status"] == "complete":
            if not _nonempty_string(row["evidence"]) or row["blocker"] != "":
                raise ContractError(f"complete outcome row {index} needs evidence and no blocker")
        elif not _nonempty_string(row["blocker"]) or row["evidence"] != "":
            raise ContractError(f"blocked outcome row {index} needs an exact blocker and no evidence")
    for field in ("constraints", "state_claims"):
        values = contract[field]
        if not isinstance(values, list) or any(not _nonempty_string(value) for value in values):
            raise ContractError(f"{field} must be a list of non-empty strings")


def _event(thread_id, contract):
    counts = {status: 0 for status in STATUSES}
    for row in contract["outcomes"]:
        counts[row["status"]] += 1
    return {
        "schema_version": 1,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": "request-contract",
        # A random id keeps two identical closeouts in the same second distinct for the uptake count.
        "event_id": secrets.token_hex(8),
        "thread_id": thread_id,
        "row_count": len(contract["outcomes"]),
        "row_status_counts": counts,
    }


def _read_regular_contract(path):
    flags = os.O_RDONLY | os.O_NONBLOCK
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("contract is not a regular file")
        with os.fdopen(descriptor, "r", encoding="utf-8") as contract_file:
            descriptor = -1
            return json.load(contract_file)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _append(path, payload):
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("event path is not a regular file")
        written = os.write(descriptor, payload)
        if written != len(payload):
            raise OSError("short append")
    finally:
        os.close(descriptor)


def _private_dir(path):
    """Create or accept a directory only this user can enter; refuse links and shared modes."""
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise OSError("fallback directory is not private to this user")


def fallback_events_path():
    """Where the event goes when the agent sandbox cannot write ~/.local/state (Codex workspace-write)."""
    base = os.environ.get("REQUEST_CONTRACT_FALLBACK_DIR") or f"/tmp/agent-quality-{os.getuid()}"
    return Path(base) / "events.jsonl"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Append metadata only for a closed request contract")
    parser.add_argument("contract", type=Path)
    parser.add_argument("--thread-id", required=True)
    args = parser.parse_args(argv)
    if not THREAD_ID.fullmatch(args.thread_id):
        parser.error("--thread-id must be a bb thread id (thr_ followed by letters or digits)")

    try:
        contract = _read_regular_contract(args.contract)
        _validate_contract(contract)
    except (OSError, UnicodeError, json.JSONDecodeError):
        print("request-contract log: could not read a valid JSON contract", file=sys.stderr)
        return 2
    except ContractError as exc:
        print(f"request-contract log: invalid contract: {exc}", file=sys.stderr)
        return 2

    path = Path.home() / ".local/state/agent-quality/events.jsonl"
    payload = (json.dumps(_event(args.thread_id, contract), separators=(",", ":")) + "\n").encode("utf-8")
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _append(path, payload)
    except OSError:
        fallback = fallback_events_path()
        try:
            _private_dir(fallback.parent)
            _append(fallback, payload)
        except OSError:
            print("request-contract log: could not append metadata event", file=sys.stderr)
            return 1
        print(f"request-contract metadata recorded in the sandbox fallback {fallback}")
        return 0
    print("request-contract metadata recorded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
