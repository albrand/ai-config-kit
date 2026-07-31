#!/usr/bin/env python3
"""Orca PR review queue helper (explicit-only, draft-only, exact-SHA).

Read-only PR queue discovery for Orca-owned review automations. This helper
NEVER posts a review, NEVER merges, and NEVER edits a PR. It computes eligible
PRIVATE DRAFT review work items, pins the exact head SHA, deduplicates against
local XDG state by exact (PR, head, reviewer), and records completed draft
outcomes via ``ack``.

Hard invariants (do not weaken):
  * Read-only against GitHub. ``gh`` is invoked via subprocess argument arrays;
    never ``shell=True``.
  * Never posts/merges/edits. Public review posting and identity verification
    belong to the caller's explicit policy, not this helper.
  * Exact-SHA semantics: a work item is pinned to the precise ``headRefOid``
    re-fetched at scan time. Dedup and ack are keyed by exact (PR, head,
    reviewer). The exact head SHA is the SOLE reopening signal: a same head
    stays suppressed regardless of author comments or any other activity; only
    a changed SHA is eligible again.
  * State is local, atomic, 0600, schema-versioned, and repository-scoped: the
    state FILENAME is a truncated SHA-256 of the explicit OWNER/REPO (or the
    resolved cwd when --repo is omitted), so separate repositories never share
    ack state. It contains no secrets, no repo URL, no branch name, no PR title,
    and no raw repo/path (only PR number, head SHA, reviewer login,
    timestamps); the filename carries only the one-way hash.

Commands:
  scan      Print eligible private draft work items as JSON (pinned exact SHA).
  precheck  Exit 0 only if eligible work exists; nonzero otherwise. Prints no
            PR details.
  ack       Record a completed draft outcome for an exact PR+head+reviewer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

SCHEMA_VERSION = 1
STATE_HASH_LEN = 16
PR_LIST_FIELDS = "number,title,state,isDraft,headRefOid,headRefName,author,reviewRequests"
FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")
GITHUB_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


class QueueStateError(RuntimeError):
    """Raised when queue state is corrupt or incompatible; fail closed."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def _home_default(sub: str) -> Path:
    return Path(os.path.expanduser("~")) / sub


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or _home_default(".local/state")
    return Path(base) / "ai-config-kit" / "orca-workflow-automation"


def _state_hash(repo: str | None) -> str:
    """Deterministic one-way hash scoping ack state to a single repository.

    Hashes the explicit OWNER/REPO, or the resolved current working directory
    when ``--repo`` is omitted. A ``repo:``/``cwd:`` tag separates the two
    namespaces so an explicit repo string can never collide with a cwd. Returns
    a truncated SHA-256 digest only; the raw repo/path is never stored or
    printed in state.
    """
    if repo:
        # GitHub OWNER/REPO identifiers are case-insensitive. Normalize them so
        # callers using different casing still share the same exact-head cursor.
        material = "repo:" + repo.casefold()
    else:
        material = "cwd:" + str(Path.cwd().resolve())
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:STATE_HASH_LEN]


def state_file(repo: str | None = None) -> Path:
    """Repository-scoped state path; the filename carries only a one-way hash."""
    return state_dir() / f"review-queue-state-{_state_hash(repo)}.json"


# --------------------------------------------------------------------------- #
# Atomic IO
# --------------------------------------------------------------------------- #
def _atomic_write_json(path: Path, data: Any, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_state(path: Path | None = None) -> dict[str, Any]:
    path = path or state_file()
    if not path.is_file():
        return {"schema_version": SCHEMA_VERSION, "records": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise QueueStateError(f"cannot read valid queue state: {path}") from exc
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != SCHEMA_VERSION
        or not isinstance(data.get("records"), dict)
    ):
        raise QueueStateError(f"incompatible queue state schema: {path}")
    for key, record in data["records"].items():
        if not isinstance(key, str) or not isinstance(record, dict):
            raise QueueStateError(f"invalid queue state record: {path}")
        pr_number = record.get("pr")
        reviewer = record.get("reviewer")
        head = record.get("head")
        if (
            not isinstance(pr_number, int)
            or pr_number < 1
            or not isinstance(reviewer, str)
            or not GITHUB_LOGIN_RE.fullmatch(reviewer)
            or not isinstance(head, str)
            or not FULL_SHA_RE.fullmatch(head)
            or key != _record_key(pr_number, reviewer)
        ):
            raise QueueStateError(f"invalid queue state record: {path}")
    return data


def save_state(data: dict[str, Any], path: Path | None = None) -> None:
    clean = {"schema_version": SCHEMA_VERSION, "records": {}}
    records = data.get("records") if isinstance(data, dict) else None
    if isinstance(records, dict):
        clean["records"] = records
    _atomic_write_json(path or state_file(), clean, mode=0o600)


# --------------------------------------------------------------------------- #
# Pure business logic (no IO, fully testable)
# --------------------------------------------------------------------------- #
def is_bot_login(login: str | None) -> bool:
    if not login:
        return False
    name = login.lower()
    return name.endswith("[bot]") or name.endswith("-bot") or name == "bot"


def normalize_pr(raw: dict[str, Any]) -> dict[str, Any]:
    author = raw.get("author") or {}
    author_login = None
    author_is_bot = False
    if isinstance(author, dict):
        author_login = author.get("login")
        if author.get("is_bot") is True:
            author_is_bot = True
    elif isinstance(author, str):
        author_login = author
    if author_login is not None:
        author_is_bot = author_is_bot or is_bot_login(author_login)

    review_requests: list[str] = []
    rr = raw.get("reviewRequests") or []
    if isinstance(rr, list):
        for item in rr:
            if isinstance(item, dict) and item.get("login"):
                review_requests.append(str(item["login"]))
            elif isinstance(item, str):
                review_requests.append(item)

    head = raw.get("headRefOid")
    return {
        "number": int(raw.get("number") or 0),
        "title": str(raw.get("title") or ""),
        "state": str(raw.get("state") or "").upper(),
        "isDraft": bool(raw.get("isDraft")),
        "headRefOid": head if isinstance(head, str) and FULL_SHA_RE.fullmatch(head) else None,
        "headRefName": raw.get("headRefName"),
        "author": author_login,
        "authorIsBot": author_is_bot,
        "reviewRequests": review_requests,
    }


def compute_eligibility(pr: dict[str, Any], reviewer: str) -> tuple[bool, str]:
    """Return (eligible, reason). Eligible implies an exact, present head SHA."""
    if pr["state"] != "OPEN":
        return False, "not-open"
    if pr["isDraft"]:
        return False, "draft-pr"
    if not pr["headRefOid"]:
        return False, "missing-head-sha"
    if pr["authorIsBot"]:
        return False, "bot-author"
    if pr["author"] == reviewer:
        return False, "self-authored"
    if reviewer not in pr["reviewRequests"]:
        return False, "not-review-requested"
    return True, "eligible"


def _record_key(pr_number: int, reviewer: str) -> str:
    return f"{pr_number}\0{reviewer}"


def compute_work_items(
    prs: Iterable[dict[str, Any]],
    reviewer: str,
    records: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (work_items, skipped). Deterministic order by PR number.

    Exact-SHA dedup: the exact head SHA is the SOLE reopening signal. A PR whose
    current head matches the acked head for the same reviewer is always
    suppressed, regardless of author comments or any other activity. Only a head
    change (different SHA) is eligible again.
    """
    ordered = sorted(prs, key=lambda p: p["number"])
    work: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for pr in ordered:
        eligible, reason = compute_eligibility(pr, reviewer)
        if not eligible:
            skipped.append({"number": pr["number"], "reason": reason})
            continue
        record = records.get(_record_key(pr["number"], reviewer))
        if isinstance(record, dict) and record.get("head") == pr["headRefOid"]:
            skipped.append({"number": pr["number"], "reason": "already-reviewed-exact-sha"})
            continue
        work.append(_work_item(pr, reviewer, "eligible"))
    return work, skipped


def _work_item(pr: dict[str, Any], reviewer: str, reason: str) -> dict[str, Any]:
    return {
        "number": pr["number"],
        "headRefOid": pr["headRefOid"],
        "headRefName": pr.get("headRefName"),
        "reviewer": reviewer,
        "reason": reason,
    }


def record_ack(
    records: dict[str, Any],
    *,
    pr_number: int,
    head: str,
    reviewer: str,
    acked_at: str | None = None,
) -> dict[str, Any]:
    if not isinstance(pr_number, int) or pr_number < 1:
        raise ValueError("ack requires a positive PR number")
    if not isinstance(head, str) or not FULL_SHA_RE.fullmatch(head):
        raise ValueError("ack requires an exact 40- or 64-character hexadecimal head SHA")
    if not isinstance(reviewer, str) or not GITHUB_LOGIN_RE.fullmatch(reviewer):
        raise ValueError("ack requires a valid GitHub reviewer login")
    entry = {
        "pr": int(pr_number),
        "reviewer": reviewer,
        "head": head,
        "acked_at": acked_at or _utc_now(),
    }
    records[_record_key(int(pr_number), reviewer)] = entry
    return entry


# --------------------------------------------------------------------------- #
# gh runner (read-only, argument arrays, no shell=True)
# --------------------------------------------------------------------------- #
GhRunner = Callable[[list[str]], str]


def default_gh_runner(args: list[str]) -> str:
    """Run ``gh`` with an argument array and return stdout. No shell=True."""
    proc = subprocess.run(
        ["gh", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def stored_account_gh_runner(reviewer: str) -> GhRunner:
    """Return a runner pinned to a stored ``gh`` account without leaking its token."""
    if not GITHUB_LOGIN_RE.fullmatch(reviewer):
        raise RuntimeError("invalid reviewer login for stored gh account")
    token_proc = subprocess.run(
        ["gh", "auth", "token", "--user", reviewer],
        check=True,
        capture_output=True,
        text=True,
    )
    token = token_proc.stdout.strip()
    if not token:
        raise RuntimeError("gh returned an empty token for the requested reviewer")
    gh_env = os.environ.copy()
    gh_env["GH_TOKEN"] = token

    def run(args: list[str]) -> str:
        proc = subprocess.run(
            ["gh", *args],
            check=True,
            capture_output=True,
            text=True,
            env=gh_env,
        )
        return proc.stdout

    return run


def fetch_active_login(runner: GhRunner) -> str:
    login = runner(["api", "user", "--jq", ".login"]).strip()
    if not GITHUB_LOGIN_RE.fullmatch(login):
        raise RuntimeError("gh returned an invalid active-user login")
    return login


def fetch_open_prs(repo: str | None, runner: GhRunner) -> list[dict[str, Any]]:
    args = ["pr", "list", "--state", "open", "--json", PR_LIST_FIELDS]
    if repo:
        args += ["--repo", repo]
    raw = runner(args)
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError(f"gh pr list returned non-JSON output: {exc}") from exc
    if not isinstance(parsed, list):
        return []
    return [normalize_pr(item) for item in parsed if isinstance(item, dict)]


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_scan(args, runner: GhRunner) -> int:
    reviewer = args.reviewer or fetch_active_login(runner)
    prs = fetch_open_prs(args.repo, runner)
    state = load_state(state_file(args.repo))
    work, skipped = compute_work_items(prs, reviewer, state.get("records", {}))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "repo": args.repo or "(current)",
        "reviewer": reviewer,
        "work_items": work,
        "skipped": skipped,
        "note": "private draft work items; no review is posted by this helper",
    }
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


def cmd_precheck(args, runner: GhRunner) -> int:
    reviewer = args.reviewer or fetch_active_login(runner)
    prs = fetch_open_prs(args.repo, runner)
    state = load_state(state_file(args.repo))
    work, _ = compute_work_items(prs, reviewer, state.get("records", {}))
    # Non-leaking: print only a generic boolean status to stderr.
    if work:
        sys.stderr.write("precheck: eligible work present\n")
        return 0
    sys.stderr.write("precheck: no eligible work\n")
    return 1


def cmd_ack(args, runner: GhRunner) -> int:
    if not args.head:
        sys.stderr.write("error: --head is required (exact headRefOid)\n")
        return 2
    reviewer = args.reviewer or fetch_active_login(runner)
    path = state_file(args.repo)
    state = load_state(path)
    record_ack(
        state.setdefault("records", {}),
        pr_number=args.pr,
        head=args.head,
        reviewer=reviewer,
    )
    save_state(state, path)
    sys.stderr.write(
        f"acked PR {args.pr} head {args.head[:12]} reviewer {reviewer}\n"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="orca-pr-review-queue.py",
        description="Read-only Orca PR review queue (private draft, exact-SHA).",
    )
    p.add_argument("--repo", default=None,
                   help="owner/repo (default: current repository)")
    p.add_argument("--reviewer", default=None,
                   help="reviewer login (default: active gh user)")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("scan", help="print eligible private draft work items as JSON")
    pre = sub.add_parser("precheck", help="exit 0 only if eligible work exists")
    pre.description = "Exit 0 only if eligible work exists; nonzero otherwise."
    ack = sub.add_parser("ack", help="record a completed draft outcome")
    ack.add_argument("--pr", type=int, required=True, help="PR number")
    ack.add_argument("--head", required=True, help="exact headRefOid at review time")
    return p


def main(argv: list[str] | None = None, runner: GhRunner | None = None) -> int:
    args = build_parser().parse_args(argv)
    gh_runner = runner or (
        stored_account_gh_runner(args.reviewer)
        if args.reviewer
        else default_gh_runner
    )
    if args.command == "scan":
        return cmd_scan(args, gh_runner)
    if args.command == "precheck":
        return cmd_precheck(args, gh_runner)
    if args.command == "ack":
        return cmd_ack(args, gh_runner)
    return 2


if __name__ == "__main__":
    sys.exit(main())
