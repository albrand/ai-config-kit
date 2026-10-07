#!/usr/bin/env python3
"""Fail-closed real production-data replay gate for Pallium data fixes."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PATHS_FILE = ROOT / "realdata-paths.json"
REPORT_NAME = "REALDATA-REPLAY.md"
HEX_SHA = re.compile(r"^[0-9a-f]{40,64}$", re.I)
HEX_256 = re.compile(r"^[0-9a-f]{64}$", re.I)
IDENTIFIERS = (
    ("ObjectId-like token", re.compile(r"(?<![0-9a-f])[0-9a-f]{24}(?![0-9a-f])", re.I)),
    ("long numeric identifier", re.compile(r"(?<![A-Fa-f0-9])\d{12,}(?![A-Fa-f0-9])")),
    ("international phone number", re.compile(r"(?<![A-Za-z0-9])\+\d(?:[\s().-]*\d){8,}(?![A-Za-z0-9])")),
    ("parenthesized phone number", re.compile(r"(?<!\d)\(\d{3}\)\s+\d{3}-\d{4}(?!\d)")),
    ("grouped phone number", re.compile(r"(?<!\d)\d{3}(?P<separator>[-.])\d{3}(?P=separator)\d{4}(?!\d)")),
    ("email address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("labelled personal field", re.compile(r"\b(?:(?:full|personal|first|last|patient|tenant|user|owner|client|contact|clinician|customer|member)[\s_-]*name|contact|email[\s_-]*address|phone(?:[\s_-]*number)?)\s*[:=]\s*[^\s,;|]+", re.I)),
    ("bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{8,}={0,2}", re.I)),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")),
    ("secret assignment", re.compile(r"\b(?:api[_-]?key|key|secret|password)\s*=\s*['\"]?[^\s,'\";]{1,}", re.I)),
)
URI = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s<>\"']+", re.I)


def validate_report_text(text: str) -> tuple[bool, str, str | None]:
    """Validate report structure, privacy and its footer."""
    for line_number, line in enumerate(text.splitlines(), start=1):
        for label, pattern in IDENTIFIERS:
            if pattern.search(line):
                return False, f"REALDATA-REPLAY.md contains disallowed {label} at line {line_number}", None
        for match in URI.finditer(line):
            try:
                parsed = urlsplit(match.group(0))
                if parsed.username is not None or parsed.password is not None:
                    return False, f"REALDATA-REPLAY.md contains credentialed URI at line {line_number}", None
            except ValueError:
                return False, f"REALDATA-REPLAY.md contains malformed URI at line {line_number}", None

    return _validate_report_structure_and_digest(text)


def git(repo: Path, *args: str, timeout: float = 4) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "git command failed").strip())
    return result.stdout.strip()


def repo_identity(repo: Path, head: str = "HEAD") -> bool:
    if repo.name.lower() == "pallium-app":
        return True
    try:
        remote = git(repo, "remote", "get-url", "origin").strip().lower()
        remote_path = urlsplit(remote).path if "://" in remote else remote
        if "@" in remote and ":" in remote and "://" not in remote:
            remote_path = remote.split(":", 1)[1]
        remote_name = remote_path.rstrip("/").rsplit("/", 1)[-1]
        if remote_name in {"pallium-app", "pallium-app.git"}:
            return True
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError):
        pass
    try:
        package = json.loads(git(repo, "show", f"{head}:package.json"))
    except (OSError, RuntimeError, subprocess.TimeoutExpired, ValueError):
        return False
    return isinstance(package, dict) and package.get("name") == "pallium-app"


def repo_root(start: Path) -> Path | None:
    try:
        return Path(git(start, "rev-parse", "--show-toplevel"))
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return None


def changed_paths(repo: Path, base: str | None, head: str = "HEAD") -> set[str]:
    paths: set[str] = set()
    if base is None:
        base = "origin/develop"
        git(repo, "rev-parse", "--verify", f"{base}^{{commit}}")
    if base:
        paths.update(filter(None, git(repo, "diff", "--name-only", f"{base}...{head}").splitlines()))
    for args in (("diff", "--name-only", "HEAD"), ("diff", "--cached", "--name-only", "HEAD")):
        paths.update(filter(None, git(repo, *args).splitlines()))
    paths.update(filter(None, git(repo, "ls-files", "--others", "--exclude-standard").splitlines()))
    return paths


def production_paths(paths: set[str]) -> set[str]:
    try:
        patterns = json.loads(PATHS_FILE.read_text(encoding="utf-8"))["patterns"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f"cannot load reviewed production-data path list: {exc}") from exc
    return {path for path in paths if any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)}


def normalized_report_hash(text: str) -> str:
    """Hash report bytes with the digest field omitted to avoid self-reference."""
    lines = [line for line in text.splitlines(keepends=True)
             if not re.match(r"^\s*[-*]?\s*Artifact SHA-256 \(excluding this line\):", line, re.I)]
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def validate_report(repo: Path, head: str) -> tuple[bool, str, str | None]:
    try:
        result = subprocess.run(["git", "show", f"{head}:{REPORT_NAME}"], cwd=repo,
                                capture_output=True, timeout=4)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"cannot read {REPORT_NAME} from reviewed head: {exc}", None
    if result.returncode:
        return False, f"missing {REPORT_NAME} at reviewed head", None
    committed_bytes = result.stdout
    path = repo / REPORT_NAME
    if path.exists():
        try:
            if path.read_bytes() != committed_bytes:
                return False, f"{REPORT_NAME} has uncommitted changes; commit the report before continuing", None
        except OSError as exc:
            return False, f"cannot compare working-tree {REPORT_NAME} with reviewed head: {exc}", None
    try:
        text = committed_bytes.decode("utf-8")
    except UnicodeError as exc:
        return False, f"cannot decode committed {REPORT_NAME}: {exc}", None
    return validate_report_text(text)


def _validate_report_structure_and_digest(text: str) -> tuple[bool, str, str | None]:
    required = {
        "copy time": r"(?im)^\s*[-*]?\s*Copy time \(UTC\):\s*\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|\+00:00)\s*$",
        "control SHA": r"(?im)^\s*[-*]?\s*Control SHA:\s*[0-9a-f]{40,64}\s*$",
        "candidate SHA": r"(?im)^\s*[-*]?\s*Candidate SHA:\s*[0-9a-f]{40,64}\s*$",
        "loopback-only local copy": r"(?im)^\s*[-*]?\s*Local copy:\s*(?:Mac|local Mac)[^\n]*loopback[^\n]*$",
        "read-only production source": r"(?im)^\s*[-*]?\s*Production source:\s*read-only\b[^\n]*$",
        "counts-only privacy": r"(?im)^\s*[-*]?\s*Privacy:\s*counts only;? no (?:row )?(?:IDs|PII)\b[^\n]*$",
        "per-goal counts/reasons/error classes": r"(?is)\|[^\n]*goal[^\n]*\|[^\n]*target[^\n]*\|[^\n]*control[^\n]*\|[^\n]*candidate[^\n]*\|[^\n]*reason[^\n]*\|[^\n]*error class[^\n]*\|",
        "blocked external-call rows": r"(?im)^\s*[-*]?\s*Blocked rows:\s*.+$",
    }
    missing = [name for name, pattern in required.items() if not re.search(pattern, text)]
    rows = [line for line in text.splitlines() if line.strip().startswith("|")]
    has_result = any(any(cell.strip() and not set(cell.strip()) <= {"-", ":"}
                         for cell in line.strip().strip("|").split("|")) for line in rows[2:])
    if len(rows) < 3 or not has_result:
        missing.append("at least one per-goal result row")
    if missing:
        return False, "REALDATA-REPLAY.md is missing required fields: " + ", ".join(missing), None
    digest_match = re.search(r"(?im)^\s*[-*]?\s*Artifact SHA-256 \(excluding this line\):\s*([0-9a-f]{64})\s*$", text)
    if not digest_match:
        return False, "REALDATA-REPLAY.md is missing its Artifact SHA-256 (excluding this line)", None
    actual = normalized_report_hash(text)
    if digest_match.group(1).lower() != actual:
        return False, ("REALDATA-REPLAY.md artifact SHA-256 does not match its contents; likely stale footer after formatting. "
                       "Run the repository formatter first, recompute the footer last, and confirm formatting leaves the bytes unchanged"), actual
    return True, "REALDATA-REPLAY.md fields and SHA-256 are valid", actual


def command_action(command: str) -> str | None:
    lower = command.lower()
    if re.search(r"(?:^|[/\\ ])pre-review\.py(?:\s|$)", command):
        return "review"
    if re.search(r"\bhermes-one(?:\.zsh)?\b|\bbb\s+fleet\s+validate\b", lower):
        return "review"
    if re.search(r"\bgh\s+pr\s+(?:ready|merge)\b", lower):
        return "pr"
    if re.search(r"\bgh\s+pr\s+create\b", lower):
        return "pr-create"
    if re.search(r"\b(?:gh\s+release\s+(?:create|edit)|release[- ]request)\b", lower):
        return "release"
    return None


def attached_texts(command: str, cwd: Path) -> tuple[list[str], list[str]]:
    texts: list[str] = []
    attached_paths: list[str] = []
    try:
        args = shlex.split(command)
    except ValueError:
        return texts, attached_paths
    for index, token in enumerate(args):
        if token in {"--evidence", "--body-file", "--notes-file", "--message-file"} and index + 1 < len(args):
            value = args[index + 1]
            evidence = Path(value)
            evidence = evidence if evidence.is_absolute() else cwd / evidence
            attached_paths.append(evidence.name)
            if evidence.is_file():
                try:
                    texts.append(evidence.read_text(encoding="utf-8"))
                except (OSError, UnicodeError):
                    pass
        elif token == "--body" and index + 1 < len(args):
            texts.append(args[index + 1])
        elif token.startswith("--body="):
            texts.append(token.split("=", 1)[1])
    return texts, attached_paths


def cited(command: str, cwd: Path, digest: str) -> bool:
    texts, attached_paths = attached_texts(command, cwd)
    names_report = any(REPORT_NAME in text for text in texts)
    includes_digest = any(digest in text for text in texts)
    direct_report_attachment = REPORT_NAME in attached_paths and includes_digest
    return direct_report_attachment or (names_report and includes_digest)


def report_attached(command: str, cwd: Path, digest: str) -> bool:
    texts, attached_paths = attached_texts(command, cwd)
    return REPORT_NAME in attached_paths and any(digest in text for text in texts)


def committed_report_has_blocked_rows(repo: Path, head: str) -> bool | None:
    try:
        result = subprocess.run(["git", "show", f"{head}:{REPORT_NAME}"], cwd=repo,
                                text=True, capture_output=True, timeout=4)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    for line in result.stdout.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip().upper() for cell in line.strip().strip("|").split("|")]
        if "BLOCKED" in cells:
            return True
    return False


def release_request_texts(command: str, cwd: Path) -> list[str]:
    texts: list[str] = []
    try:
        args = shlex.split(command)
    except ValueError:
        return texts
    for index, token in enumerate(args):
        if token not in {"--body", "--body-file", "--notes", "--notes-file", "--message-file"} or index + 1 >= len(args):
            continue
        value = args[index + 1]
        if token == "--body":
            texts.append(value)
            continue
        path = Path(value)
        path = path if path.is_absolute() else cwd / path
        if path.is_file():
            try:
                texts.append(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                pass
    return texts


def release_readback_and_rollback_cited(command: str, cwd: Path) -> bool:
    request = "\n".join(release_request_texts(command, cwd))
    has_readback = re.search(r"\bread[- ]?back\b", request, re.I)
    has_offset = re.search(r"\+\s*\d{1,3}\s*(?:min(?:ute)?s?)?\b", request, re.I)
    has_counts = re.search(r"\bcounts?\b", request, re.I)
    rollback_target = re.search(r"\brollback\b[^\n]*(?:\b[0-9a-f]{7,64}\b|\bdpl_[A-Za-z0-9]+\b)",
                                request, re.I)
    return bool(has_readback and has_offset and has_counts and rollback_target)


def github_repo_slug(repo: Path) -> str | None:
    try:
        remote = git(repo, "remote", "get-url", "origin")
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return None
    if remote.startswith("git@github.com:"):
        path = remote.split(":", 1)[1]
    else:
        parsed = urlsplit(remote)
        if (parsed.hostname or "").lower() != "github.com":
            return None
        path = parsed.path.lstrip("/")
    slug = path.removesuffix(".git").strip("/")
    return slug if len(slug.split("/")) == 2 and all(slug.split("/")) else None


def repo_flag(args: list[str]) -> str | None:
    for index, token in enumerate(args):
        if token in {"-R", "--repo"} and index + 1 < len(args):
            return args[index + 1]
        if token.startswith("--repo="):
            return token.split("=", 1)[1]
        if token.startswith("-R") and token != "-R":
            return token[2:]
    return None


def gh_json(result: subprocess.CompletedProcess[str]) -> dict[str, Any] | None:
    if result.returncode:
        return None
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("files"), list) else None


def logged_in_github_accounts() -> list[str]:
    clean_env = os.environ.copy()
    clean_env.pop("GH_TOKEN", None)
    clean_env.pop("GITHUB_TOKEN", None)
    try:
        result = subprocess.run(["gh", "auth", "status", "--hostname", "github.com"],
                                text=True, capture_output=True, timeout=5, env=clean_env)
    except (OSError, subprocess.TimeoutExpired):
        return []
    status_text = result.stdout + "\n" + result.stderr
    accounts = re.findall(r"(?im)^\s*[✓✔-]?\s*Logged in to github\.com account\s+([^\s(]+)", status_text)
    return list(dict.fromkeys(accounts))


def pull_request_info(repo: Path, command: str) -> dict[str, Any] | None:
    try:
        args = shlex.split(command)
    except ValueError:
        args = []
    reference: str | None = None
    for index in range(max(0, len(args) - 1)):
        if args[index:index + 2] == ["pr", "ready"] or args[index:index + 2] == ["pr", "merge"]:
            if index + 2 < len(args) and not args[index + 2].startswith("-"):
                reference = args[index + 2]
            break
    query = ["gh", "pr", "view"]
    if reference:
        query.append(reference)
    target_repo = repo_flag(args) or github_repo_slug(repo)
    if target_repo:
        query.extend(["--repo", target_repo])
    query.extend(["--json", "body,headRefOid,files"])
    try:
        result = subprocess.run(query, cwd=repo, text=True, capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        result = None
    data = gh_json(result) if result is not None else None
    if data is not None:
        return data

    clean_env = os.environ.copy()
    clean_env.pop("GH_TOKEN", None)
    clean_env.pop("GITHUB_TOKEN", None)
    for login in logged_in_github_accounts():
        try:
            token_result = subprocess.run(["gh", "auth", "token", "--user", login],
                                          text=True, capture_output=True, timeout=5, env=clean_env)
        except (OSError, subprocess.TimeoutExpired):
            continue
        token = token_result.stdout.strip() if token_result.returncode == 0 else ""
        if not token:
            continue
        account_env = os.environ.copy()
        account_env.pop("GITHUB_TOKEN", None)
        account_env["GH_TOKEN"] = token
        try:
            result = subprocess.run(query, cwd=repo, text=True, capture_output=True,
                                    timeout=5, env=account_env)
        except (OSError, subprocess.TimeoutExpired):
            result = None
        token = ""
        data = gh_json(result) if result is not None else None
        if data is not None:
            return data
    return None


def evaluate(repo: Path, base: str | None, action: str, command: str = "", cwd: Path | None = None,
             head: str = "HEAD") -> tuple[bool, str, set[str], str | None]:
    cwd = cwd or repo
    if not repo_identity(repo, head):
        return True, "not the Pallium app repository", set(), None
    pr_info: dict[str, Any] | None = None
    try:
        if action == "pr":
            pr_info = pull_request_info(repo, command)
            if pr_info is None:
                return False, "cannot read the target PR's changed files; refusing to guess", set(), None
            pr_paths = {str(item.get("path")) for item in pr_info["files"]
                        if isinstance(item, dict) and item.get("path")}
            impacted = production_paths(pr_paths)
        else:
            impacted = production_paths(changed_paths(repo, base, head))
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return False, f"cannot establish the Pallium production-data diff: {exc}", set(), None
    if not impacted:
        return True, "no production-data paths changed", set(), None
    if action == "pr" and str(pr_info.get("headRefOid") or "").lower() != git(repo, "rev-parse", head).lower():
        return False, "run the PR-ready or merge gate from the worktree at the exact target PR head", impacted, None
    valid, reason, digest = validate_report(repo, head)
    if not valid or digest is None:
        return False, reason, impacted, digest
    if action == "review":
        # pre-review creates the packet that cites the report; Hermes itself must attach it.
        if "pre-review.py" not in command and not report_attached(command, cwd, digest):
            return False, f"Hermes evidence must attach {REPORT_NAME} with its SHA-256", impacted, digest
    elif action in {"pr", "pr-create", "release"}:
        try:
            git(repo, "cat-file", "-e", f"{head}:{REPORT_NAME}")
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            return False, f"{REPORT_NAME} must be committed for PR-ready, merge, or release", impacted, digest
        if action == "release":
            blocked_rows = committed_report_has_blocked_rows(repo, head)
            if blocked_rows is None:
                return False, f"cannot determine whether committed {REPORT_NAME} contains blocked rows", impacted, digest
            if blocked_rows and not release_readback_and_rollback_cited(command, cwd):
                return False, ("release request for blocked rows must name the post-release read-back offset and counts, "
                               "plus a rollback SHA or deployment ID"), impacted, digest
        if action == "pr" and not (REPORT_NAME in str(pr_info.get("body") or "")
                                    and digest in str(pr_info.get("body") or "")):
            return False, f"the current PR body must cite {REPORT_NAME} and its SHA-256", impacted, digest
        if action in {"pr-create", "release"} and not cited(command, cwd, digest):
            return False, f"the PR or release request must cite {REPORT_NAME} and its SHA-256", impacted, digest
    return True, "real production-data replay evidence and citation are present", impacted, digest


def hook() -> int:
    try:
        payload: dict[str, Any] = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                    "permissionDecisionReason": "[realdata-replay-gate] invalid hook payload; review or release denied"}}))
        return 2
    tool_input = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    command = str(tool_input.get("command") or tool_input.get("cmd") or "")
    action = command_action(command)
    if not action:
        return 0
    cwd = Path(str(payload.get("cwd") or payload.get("working_directory") or os.getcwd())).resolve()
    repo = repo_root(cwd)
    if repo is None or not repo_identity(repo):
        return 0
    ok, reason, impacted, digest = evaluate(repo, None, action, command, cwd)
    if ok:
        return 0
    detail = ", ".join(sorted(impacted)) or "diff unknown"
    message = f"[realdata-replay-gate] {reason}; affected paths: {detail}. Complete and cite the read-only Mac loopback replay before review or release."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                "permissionDecisionReason": message}}))
    print(message, file=sys.stderr)
    return 2


def main() -> int:
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="mode", required=True)
    subs.add_parser("hook")
    check = subs.add_parser("check")
    check.add_argument("--repo", type=Path, required=True)
    check.add_argument("--base")
    check.add_argument("--action", choices=("review", "pr", "pr-create", "release"), default="review")
    check.add_argument("--command", default="pre-review.py")
    check.add_argument("--cwd", type=Path)
    check.add_argument("--head", default="HEAD")
    check.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.mode == "hook":
        return hook()
    repo = repo_root(args.repo.resolve())
    if repo is None:
        print("[realdata-replay-gate] not inside a git worktree", file=sys.stderr)
        return 2
    ok, reason, impacted, digest = evaluate(repo, args.base, args.action, args.command,
                                            args.cwd.resolve() if args.cwd else repo, args.head)
    if args.json:
        print(json.dumps({"allowed": ok, "reason": reason, "affected_paths": sorted(impacted),
                          "artifact": REPORT_NAME if impacted and digest else None, "sha256": digest}))
    else:
        print(f"[realdata-replay-gate] {'ALLOW' if ok else 'DENY'}: {reason}")
        if impacted:
            print("affected paths: " + ", ".join(sorted(impacted)))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
