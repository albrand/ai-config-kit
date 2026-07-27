#!/usr/bin/env python3
"""Orca execution productivity ledger (append-only JSONL, privacy-safe).

Records bounded execution telemetry for Orca-owned automations and summarizes
aggregates. Measures **quality and validation outcomes**, never token/speed
rankings alone.

Hard invariants (do not weaken):
  * Write-time schema validation with an allowlist. Unknown fields are rejected.
  * Forbidden fields are always rejected: prompt/transcript, env values (and any
    ``env_*`` key), repo URL/repository, branch, sha/head/commit, diff/patch,
    and secret/token/credential material. None of these are ever stored.
  * The ledger file is created 0600 and append-safe. The default path is
    ``$XDG_DATA_HOME/ai-config-kit/orca-workflow-automation/executions.jsonl``.
  * Summary emits aggregates only after a configurable minimum sample count
    (default 5); route/skill recommendations appear only when the threshold is
    met.

Commands:
  record    Validate and append one JSONL row.
  summary   Print aggregate statistics as JSON.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# Allowlist of user-supplied fields. Anything not here is rejected.
ALLOWED_FIELDS = {
    "route": (str,),
    "model": (str,),
    "provider": (str,),
    "skill": (str,),
    "tool": (str,),
    "elapsed": (int, float),
    "validation": (str,),
    "retries": (int,),
    "repair": (int,),
    "outcome": (str,),
    "scope_drift": (bool,),
    "cost": (int, float),
}

ALLOWED_VALIDATION = {"pass", "fail", "skipped", "not_run"}
ALLOWED_OUTCOME = {"success", "failure", "blocked"}

# Forbidden field names (compared case-insensitively) and a forbidden prefix.
FORBIDDEN_FIELDS = {
    "prompt", "prompts", "prompt_text", "messages", "message",
    "transcript", "transcripts", "history",
    "env", "environment",
    "repo_url", "repository_url", "repo", "repository", "url", "base_url",
    "branch", "ref", "ref_name",
    "sha", "head", "head_sha", "commit", "oid", "head_ref_oid",
    "diff", "patch", "content", "body",
    "secret", "token", "key", "password", "credential", "credentials",
    "api_key", "access_token", "auth",
}
FORBIDDEN_PREFIXES = ("env_", "secret_", "token_")
CATEGORICAL_FIELDS = {"route", "model", "provider", "skill", "tool"}
CATEGORICAL_RE = re.compile(r"^[A-Za-z0-9_.:/@+-]{1,128}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def _home_default(sub: str) -> Path:
    return Path(os.path.expanduser("~")) / sub


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or _home_default(".local/share")
    return Path(base) / "ai-config-kit" / "orca-workflow-automation"


def ledger_file() -> Path:
    return data_dir() / "executions.jsonl"


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
class RecordError(ValueError):
    """Raised when a record violates the schema/allowlist/forbidden rules."""


def validate_record(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate a user-supplied record. Returns the cleaned record.

    Raises RecordError on unknown or forbidden fields or bad value types.
    Never returns data containing forbidden fields.
    """
    if not isinstance(raw, dict):
        raise RecordError("record must be a JSON object")
    cleaned: dict[str, Any] = {}
    for key, value in raw.items():
        name = str(key)
        lname = name.lower()
        if name in FORBIDDEN_FIELDS or lname in FORBIDDEN_FIELDS:
            raise RecordError(f"forbidden field: {name}")
        if any(lname.startswith(p) for p in FORBIDDEN_PREFIXES):
            raise RecordError(f"forbidden field prefix: {name}")
        if name not in ALLOWED_FIELDS:
            raise RecordError(f"unknown field: {name}")
        expected = ALLOWED_FIELDS[name]
        # bool is a subclass of int; reject it for every numeric field.
        if name in {"elapsed", "retries", "repair", "cost"} and isinstance(value, bool):
            raise RecordError(f"field {name} must be numeric, not bool")
        if not isinstance(value, expected):
            raise RecordError(
                f"field {name} must be {'|'.join(t.__name__ for t in expected)}, "
                f"got {type(value).__name__}"
            )
        if name == "validation" and value not in ALLOWED_VALIDATION:
            raise RecordError(
                f"validation must be one of {sorted(ALLOWED_VALIDATION)}, got {value!r}"
            )
        if name == "outcome" and value not in ALLOWED_OUTCOME:
            raise RecordError(
                f"outcome must be one of {sorted(ALLOWED_OUTCOME)}, got {value!r}"
            )
        if name in CATEGORICAL_FIELDS and not CATEGORICAL_RE.fullmatch(value):
            raise RecordError(
                f"field {name} must be a 1-128 character categorical identifier"
            )
        if name in ("retries", "repair") and value < 0:
            raise RecordError(f"field {name} must be >= 0")
        if name == "elapsed" and value < 0:
            raise RecordError("field elapsed must be >= 0")
        if name == "cost" and value < 0:
            raise RecordError("field cost must be >= 0")
        if name in {"elapsed", "cost"} and not math.isfinite(float(value)):
            raise RecordError(f"field {name} must be finite")
        cleaned[name] = value
    return cleaned


def _envelope(cleaned: dict[str, Any]) -> dict[str, Any]:
    row = {"schema_version": SCHEMA_VERSION, "recorded_at": _utc_now()}
    row.update(cleaned)
    return row


# --------------------------------------------------------------------------- #
# IO (append-only, 0600)
# --------------------------------------------------------------------------- #
def append_row(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)
    # Ensure restrictive mode even if the file pre-existed with looser bits.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def read_rows(path: Path) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    parse_errors = 0
    if not path.is_file():
        return rows, 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                parse_errors += 1
                continue
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                parse_errors += 1
    return rows, parse_errors


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return statistics.median(values)


def _rate(rows: list[dict[str, Any]], field: str, value: Any) -> float:
    if not rows:
        return 0.0
    hit = sum(1 for r in rows if r.get(field) == value)
    return hit / len(rows)


def _group_aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed = [float(r["elapsed"]) for r in rows if isinstance(r.get("elapsed"), (int, float))]
    return {
        "count": len(rows),
        "elapsed_median": _median(elapsed),
        "success_rate": _rate(rows, "outcome", "success"),
        "validated_rate": _rate(rows, "validation", "pass"),
        "retries": sum(int(r.get("retries") or 0) for r in rows),
        "repair": sum(int(r.get("repair") or 0) for r in rows),
        "scope_drift": sum(1 for r in rows if r.get("scope_drift") is True),
    }


def _by_field(rows: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key in sorted({str(r.get(field)) for r in rows if r.get(field) is not None}):
        subset = [r for r in rows if str(r.get(field)) == key]
        out[key] = _group_aggregate(subset)
    return out


def recommendations(by_route: dict[str, dict[str, Any]], min_subgroup: int = 3,
                    repair_rate_alert: float = 0.5) -> list[str]:
    recs: list[str] = []
    for route, agg in by_route.items():
        if agg["count"] >= min_subgroup and agg["success_rate"] > 0 and agg["repair"] / agg["count"] >= repair_rate_alert:
            recs.append(
                f"route '{route}' has a high repair rate "
                f"({agg['repair']}/{agg['count']}); review prompt/tooling quality"
            )
        if agg["count"] >= min_subgroup and agg.get("validated_rate", 0.0) < 0.5:
            recs.append(
                f"route '{route}' has low validation rate "
                f"({agg['validated_rate']:.2f}); strengthen pre/post checks"
            )
    return recs


def summarize(rows: list[dict[str, Any]], *, min_samples: int = 5) -> dict[str, Any]:
    if min_samples < 1:
        raise ValueError("min_samples must be >= 1")
    overall = _group_aggregate(rows)
    sufficient = len(rows) >= min_samples
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "count": len(rows),
        "min_samples": min_samples,
        "sufficient": sufficient,
        "aggregates": overall if sufficient else None,
        "by_route": _by_field(rows, "route") if sufficient else {},
        "by_skill": _by_field(rows, "skill") if sufficient else {},
        "recommendations": recommendations(_by_field(rows, "route")) if sufficient else [],
    }
    return payload


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_record(args) -> int:
    try:
        data = json.loads(args.json)
    except ValueError as exc:
        sys.stderr.write(f"error: invalid JSON: {exc}\n")
        return 2
    try:
        cleaned = validate_record(data)
    except RecordError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    append_row(ledger_file(), _envelope(cleaned))
    sys.stderr.write("recorded 1 execution row\n")
    return 0


def cmd_summary(args) -> int:
    rows, parse_errors = read_rows(ledger_file())
    payload = summarize(rows, min_samples=args.min_samples)
    payload["parse_errors"] = parse_errors
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="execution-ledger.py",
        description="Privacy-safe execution productivity ledger (JSONL).",
    )
    sub = p.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="validate and append one JSONL row")
    rec.add_argument("json", help="JSON object with allowlisted fields only")
    summ = sub.add_parser("summary", help="print aggregate statistics as JSON")
    summ.add_argument("--min-samples", type=int, default=5,
                      help="minimum sample count for aggregates/recommendations (default 5)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "record":
        return cmd_record(args)
    if args.command == "summary":
        return cmd_summary(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
