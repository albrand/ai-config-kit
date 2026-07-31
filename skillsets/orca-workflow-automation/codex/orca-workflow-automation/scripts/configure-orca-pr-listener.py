#!/usr/bin/env python3
"""Repo-agnostic Orca PR-listener configurator (explicit-only, disabled-first).

Builds, inspects, and reconciles an Orca-owned scheduled PR-review automation
for **any single Orca-registered GitHub repository**. This configurator is
installed per repo; there is no bulk activation.

Hard invariants (do not weaken):
  * Orca is invoked via ``subprocess`` argument arrays only, never through a
    shell. The precheck command handed to Orca is a fixed, shell-quoted command
    referencing the sibling queue helper with exact repo/reviewer.
  * Default install is **disabled**. ``--enable`` is opt-in.
  * The automation prompt embeds a deterministic marker
    ``[orca-pr-listener:v1 repo=OWNER/REPO reviewer=LOGIN]`` and never grants a
    GitHub write primitive. It requires private/draft-only output, exact head
    SHA pinning, a generic authoritative board (never hardcoded to GitHub
    Projects), and no posting/commenting/merging/editing of GitHub state.
  * Idempotent: ``install`` edits only an existing automation whose marker and
    resolved repo identity both match. Same-name collisions and marker/target
    mismatches are refused, never silently overwritten. No ``remove`` command.
  * ``plan`` and ``status`` are read-only. ``install`` mutates Orca only.
  * No repo URLs, secrets, or branch names are persisted in telemetry/state.
    The single-writer lock stores only a PID and an ISO-8601 timestamp.

Commands:
  plan      Resolve inputs read-only and print the deterministic plan as JSON.
  install   Create or reconcile the automation (disabled unless --enable).
  status    Read-only: print the current automation state for this target.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA_VERSION = 1

MARKER_PREFIX = "[orca-pr-listener:v1"
MARKER_RE = re.compile(
    r"\[orca-pr-listener:v1 repo=(?P<repo>[^\s\]]+) reviewer=(?P<reviewer>[^\s\]]+)\]"
)
GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
GITHUB_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
NAME_SAFE_RE = re.compile(r"[^a-z0-9]+")
SELECTOR_RE = re.compile(r"^(?:id|name|path):.+$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
SAFE_TIMEZONE_RE = re.compile(r"^[A-Za-z0-9._+/-]{1,128}$")
PRECHECK_TIMEOUT = 30
SIBLING_HELPER = "orca-pr-review-queue.py"
CLEANUP_HELPER = "orca-automation-workspace-cleanup.py"

BOARD_POLICIES = ("required",)
TRIGGERS = ("hourly", "daily", "weekly")


class ConfiguratorError(RuntimeError):
    """Expected failure (bad input, ambiguous repo, collision). Exit code 2."""


class LockBusy(RuntimeError):
    """Another configurator holds the single-writer lock. Exit code 75."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _home_default(sub: str) -> Path:
    return Path(os.path.expanduser("~")) / sub


def _script_dir() -> Path:
    return Path(__file__).resolve().parent


def sibling_helper_path() -> Path:
    return _script_dir() / SIBLING_HELPER


def cleanup_helper_path() -> Path:
    return _script_dir() / CLEANUP_HELPER


# --------------------------------------------------------------------------- #
# Orca runner (argument arrays; never shell)
# --------------------------------------------------------------------------- #
OrcaRunner = Callable[[list[str]], str]


def default_orca_runner(args: list[str]) -> str:
    """Run ``orca`` with an argument array, never through a shell."""
    proc = subprocess.run(
        ["orca", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


# --------------------------------------------------------------------------- #
# Single-writer lock (atomic create, stale-safe). Stores no repo data.
# --------------------------------------------------------------------------- #
def lock_path_default() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or _home_default(".local/state")
    return Path(base) / "ai-config-kit" / "orca-workflow-automation" / "configure.lock"


class SingleWriterLock:
    """Atomic lock via ``O_CREAT|O_EXCL``. Stale entries may be reclaimed."""

    def __init__(self, path: Path, stale_seconds: int = 3600) -> None:
        self.path = path
        self.stale_seconds = stale_seconds
        self._owned = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except OSError as exc:
                if exc.errno != errno.EEXIST:
                    raise
                if not self._reclaim_if_stale():
                    raise LockBusy(f"another configurator holds the lock: {self.path}")
                continue
            try:
                payload = json.dumps(
                    {"pid": os.getpid(), "acquired_at": _utc_now()},
                    separators=(",", ":"),
                )
                os.write(fd, payload.encode("utf-8"))
            finally:
                os.close(fd)
            self._owned = True
            return
        raise LockBusy(f"could not acquire lock: {self.path}")

    def _reclaim_if_stale(self) -> bool:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        acquired = data.get("acquired_at")
        if isinstance(acquired, str):
            try:
                ts = datetime.fromisoformat(acquired.replace("Z", "+00:00"))
            except ValueError:
                ts = None
            if ts is not None:
                age = (datetime.now(timezone.utc) - ts).total_seconds()
                if age >= self.stale_seconds:
                    try:
                        os.unlink(self.path)
                    except OSError:
                        return False
                    return True
        return False

    def release(self) -> None:
        if not self._owned:
            return
        try:
            os.unlink(self.path)
        except OSError:
            pass
        self._owned = False

    def __enter__(self) -> "SingleWriterLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def validate_github_repo(repo: str) -> str:
    if not isinstance(repo, str) or not GITHUB_REPO_RE.fullmatch(repo):
        raise ConfiguratorError(
            "--github-repo must be OWNER/REPO (alphanumerics, . _ - only)"
        )
    return repo


def validate_reviewer(login: str) -> str:
    if not isinstance(login, str) or not GITHUB_LOGIN_RE.fullmatch(login):
        raise ConfiguratorError("--reviewer must be a valid GitHub login")
    return login


def validate_repo_path(path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        raise ConfiguratorError("--repo-path must be an absolute path")
    return p


def validate_orca_selector(selector: str) -> str:
    if not isinstance(selector, str) or not SELECTOR_RE.fullmatch(selector):
        raise ConfiguratorError(
            "--orca-repo must be a selector like id:<ID>, name:<NAME>, or path:<PATH>"
        )
    return selector


def validate_board_policy(policy: str) -> str:
    if policy not in BOARD_POLICIES:
        raise ConfiguratorError(
            f"--board-policy must be one of {BOARD_POLICIES}"
        )
    return policy


def validate_base_branch(ref: str) -> str:
    invalid = (
        not ref
        or len(ref) > 255
        or ref.startswith(("/", "."))
        or ref.endswith(("/", ".", ".lock"))
        or "//" in ref
        or ".." in ref
        or "@{" in ref
        or any(ch.isspace() or ord(ch) < 32 for ch in ref)
        or any(ch in ref for ch in "~^:?*[\\")
    )
    if invalid:
        raise ConfiguratorError("base branch is not a safe Git ref")
    return ref


def validate_provider(provider: str) -> str:
    if not SAFE_ID_RE.fullmatch(provider):
        raise ConfiguratorError("--provider must be a safe agent identifier")
    return provider


def validate_timezone(timezone: str | None) -> str | None:
    if timezone is not None and not SAFE_TIMEZONE_RE.fullmatch(timezone):
        raise ConfiguratorError("--timezone must be a safe IANA timezone")
    return timezone


# --------------------------------------------------------------------------- #
# Deterministic identity
# --------------------------------------------------------------------------- #
def _slug(value: str) -> str:
    slug = NAME_SAFE_RE.sub("-", value.lower()).strip("-")
    return slug or "x"


def deterministic_name(github_repo: str, reviewer: str) -> str:
    owner, _, repo = github_repo.partition("/")
    return f"orca-pr-listener-{_slug(owner)}-{_slug(repo)}-{_slug(reviewer)}"


def marker(github_repo: str, reviewer: str) -> str:
    return f"{MARKER_PREFIX} repo={github_repo} reviewer={reviewer}]"


# --------------------------------------------------------------------------- #
# Repo resolution
# --------------------------------------------------------------------------- #
def _canonical_repo(raw: dict[str, Any]) -> dict[str, Any]:
    remote = raw.get("gitRemoteIdentity")
    canonical_key = remote.get("canonicalKey") if isinstance(remote, dict) else None
    github_repo = None
    if isinstance(canonical_key, str) and canonical_key.startswith("github.com/"):
        github_repo = canonical_key.removeprefix("github.com/")
    icon = raw.get("repoIcon")
    if github_repo is None and isinstance(icon, dict) and icon.get("source") == "github":
        label = icon.get("label")
        if isinstance(label, str) and GITHUB_REPO_RE.fullmatch(label):
            github_repo = label
    return {
        "id": raw.get("id") or raw.get("repoId") or raw.get("uuid"),
        "name": raw.get("name") or raw.get("displayName") or raw.get("fullName"),
        "path": raw.get("path") or raw.get("worktreePath") or raw.get("localPath"),
        "worktreeBaseRef": raw.get("worktreeBaseRef") or raw.get("baseBranch")
        or raw.get("defaultBranch"),
        "githubRepo": github_repo,
    }


def fetch_repos(runner: OrcaRunner) -> list[dict[str, Any]]:
    raw = runner(["repo", "list", "--json"])
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise ConfiguratorError(f"orca repo list returned non-JSON output: {exc}") from exc
    if isinstance(parsed, dict):
        result = parsed.get("result")
        items = result.get("repos", []) if isinstance(result, dict) else []
    else:
        items = parsed if isinstance(parsed, list) else []
    return [_canonical_repo(r) for r in items if isinstance(r, dict)]


def resolve_repo(
    repo_path: str | None,
    orca_selector: str | None,
    runner: OrcaRunner,
) -> dict[str, Any]:
    if not repo_path and not orca_selector:
        raise ConfiguratorError(
            "provide exactly one of --repo-path or --orca-repo"
        )
    if repo_path and orca_selector:
        raise ConfiguratorError(
            "provide --repo-path OR --orca-repo, not both"
        )
    repos = fetch_repos(runner)
    if repo_path:
        target = validate_repo_path(repo_path)
        matches = [r for r in repos if r.get("path") and Path(r["path"]) == target]
        if not matches:
            raise ConfiguratorError(f"no Orca repo at path: {target}")
    else:
        assert orca_selector is not None
        validate_orca_selector(orca_selector)
        kind, _, value = orca_selector.partition(":")
        field = {"id": "id", "name": "name", "path": "path"}[kind]
        if field == "path":
            matches = [r for r in repos if r.get("path") and Path(r["path"]) == Path(value)]
        else:
            matches = [r for r in repos if r.get(field) == value]
        if not matches:
            raise ConfiguratorError(f"no Orca repo matching selector: {orca_selector}")
    if len(matches) > 1:
        raise ConfiguratorError(
            f"ambiguous Orca repo target: {len(matches)} matches"
        )
    repo = matches[0]
    if not repo.get("id"):
        raise ConfiguratorError("resolved Orca repo has no id; cannot target it")
    return repo


def resolve_base_branch(repo: dict[str, Any], override: str | None) -> str:
    if override:
        return validate_base_branch(override)
    base = repo.get("worktreeBaseRef")
    if not isinstance(base, str) or not base.strip():
        raise ConfiguratorError(
            "repo has no worktreeBaseRef; pass --base-branch explicitly"
        )
    return validate_base_branch(base)


def verify_github_binding(repo: dict[str, Any], github_repo: str) -> None:
    registered = repo.get("githubRepo")
    if not isinstance(registered, str):
        raise ConfiguratorError(
            "resolved Orca repo has no verified GitHub remote identity"
        )
    if registered.casefold() != github_repo.casefold():
        raise ConfiguratorError(
            f"--github-repo does not match the Orca repo remote ({registered})"
        )


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #
def build_prompt(
    github_repo: str,
    reviewer: str,
    board_policy: str,
    base_branch: str,
    enable_hermes_critique: bool = False,
    cleanup_command: str | None = None,
) -> str:
    head = marker(github_repo, reviewer)
    lines: list[str] = []
    lines.append(head)
    lines.append("")
    lines.append(
        "Use $orca-workflow-automation and $high-signal-pr-review together. "
        "Scan exactly the GitHub repo "
        f"{github_repo} for review requests on the active reviewer {reviewer} only."
    )
    lines.append(
        "Pin the exact headRefOid for every PR; re-fetch it immediately before any "
        "review output. If the exact SHA is missing, stop and report nothing."
    )
    lines.append(
        "Produce PRIVATE DRAFT review output only. Never post a review, never "
        "comment, never merge, never edit any PR, branch, or GitHub resource."
    )
    lines.append(
        "Use a fresh Orca worktree/workspace and a fresh session per run; one "
        f"writer per worktree. Base branch: {base_branch}."
    )
    lines.append(
        "Apply the board-backed regression gate against an authoritative board of "
        "record (the team's accepted/Done/released behavior). Do NOT hardcode "
        "GitHub Projects as the board; treat the generic authoritative board as "
        "the source of working behavior."
    )
    lines.append(
        "Board policy REQUIRED: if the authoritative board cannot be reached "
        "or is unavailable, completion is BLOCKED (do not finish, do not post)."
    )
    lines.append(
        "Ack the exact (PR, head SHA, reviewer) ONLY after validation completes. "
        "Record aggregate execution telemetry only (outcome/validation/route); "
        "never record prompts, transcripts, env values, secrets, repo URL, "
        "branch, or SHA."
    )
    if enable_hermes_critique:
        lines.append(
            "Optional: request one bounded, read-only Hermes critique of the plan; "
            "the master thread validates every Hermes result. No reverse SSH, no "
            "listeners, no environment forwarding."
        )
    if cleanup_command:
        lines.append("")
        lines.append(
            "FINAL ACTION (post-result workspace cleanup): run this exact command "
            "only after at least one substantive review is complete and validated, "
            "as the very last shell action immediately before emitting your final "
            "private output. Do not run it when the run stops with only blocked, "
            "partial, stale-head, or unvalidated work:"
        )
        lines.append(f"  {cleanup_command}")
        lines.append(
            "This spawns a detached watcher that removes only this run's "
            "new-per-run workspace AFTER Orca has persisted the run output: it "
            "waits for a run with this exact workspaceId to reach status "
            "completed with a non-empty outputSnapshot, then removes the exact "
            "worktree. Deletion is fail-closed: blocked, partial, stale, "
            "unposted, or timed-out runs leave the workspace in place. This "
            "changes nothing about output: keep PRIVATE DRAFT output only and "
            "never post, comment, merge, or edit any PR, branch, or GitHub "
            "resource."
        )
    return "\n".join(lines)


def build_precheck_command(
    helper_abs: Path, github_repo: str, reviewer: str
) -> str:
    """Fixed argument-array shape handed to Orca. Validated tokens only."""
    if not GITHUB_REPO_RE.fullmatch(github_repo):
        raise ConfiguratorError("invalid github repo in precheck")
    if not GITHUB_LOGIN_RE.fullmatch(reviewer):
        raise ConfiguratorError("invalid reviewer in precheck")
    return shlex.join(
        [
            "python3",
            str(helper_abs),
            "--repo",
            github_repo,
            "--reviewer",
            reviewer,
            "precheck",
        ]
    )


def build_cleanup_command(
    helper_abs: Path,
    name: str,
    github_repo: str,
    reviewer: str,
    repo_id: str,
) -> str:
    """Fixed final-arm command handed to the automation prompt.

    Exact, deterministic tokens only: the cleanup helper absolute path, the
    deterministic automation name, the marker identity (repo/reviewer), and the
    exact Orca repo id. Built with ``shlex.join`` so no validated token can
    introduce shell metacharacters.
    """
    if not GITHUB_REPO_RE.fullmatch(github_repo):
        raise ConfiguratorError("invalid github repo in cleanup command")
    if not GITHUB_LOGIN_RE.fullmatch(reviewer):
        raise ConfiguratorError("invalid reviewer in cleanup command")
    if not isinstance(name, str) or not name:
        raise ConfiguratorError("invalid automation name in cleanup command")
    if not SAFE_ID_RE.fullmatch(repo_id):
        raise ConfiguratorError("invalid repo id in cleanup command")
    return shlex.join(
        [
            "python3",
            str(helper_abs),
            "--automation-name",
            name,
            "--github-repo",
            github_repo,
            "--reviewer",
            reviewer,
            "--orca-repo",
            f"id:{repo_id}",
            "watch",
        ]
    )


# --------------------------------------------------------------------------- #
# Automation argv builders
# --------------------------------------------------------------------------- #
def _common_field_args(
    *,
    name: str,
    prompt: str,
    repo_id: str,
    trigger: str,
    provider: str,
    base_branch: str,
    precheck: str,
    timezone: str | None,
) -> list[str]:
    args = [
        "--name", name,
        "--trigger", trigger,
        "--provider", provider,
        "--repo", f"id:{repo_id}",
        "--workspace-mode", "new-per-run",
        "--base-branch", base_branch,
        "--fresh-session",
        "--precheck", precheck,
        "--precheck-timeout", str(PRECHECK_TIMEOUT),
        "--prompt", prompt,
    ]
    if timezone:
        args += ["--timezone", timezone]
    return args


def build_create_argv(
    *,
    name: str,
    prompt: str,
    repo_id: str,
    trigger: str,
    provider: str,
    base_branch: str,
    precheck: str,
    timezone: str | None,
    enabled: bool,
) -> list[str]:
    args = ["automations", "create"]
    args.append("--enabled" if enabled else "--disabled")
    args += _common_field_args(
        name=name, prompt=prompt, repo_id=repo_id, trigger=trigger,
        provider=provider, base_branch=base_branch, precheck=precheck,
        timezone=timezone,
    )
    return args


def build_edit_argv(
    *,
    automation_id: str,
    name: str,
    prompt: str,
    repo_id: str,
    trigger: str,
    provider: str,
    base_branch: str,
    precheck: str,
    timezone: str | None,
    enabled: bool,
) -> list[str]:
    args = ["automations", "edit", automation_id]
    args.append("--enabled" if enabled else "--disabled")
    args += _common_field_args(
        name=name, prompt=prompt, repo_id=repo_id, trigger=trigger,
        provider=provider, base_branch=base_branch, precheck=precheck,
        timezone=timezone,
    )
    return args


# --------------------------------------------------------------------------- #
# Automation list / matching
# --------------------------------------------------------------------------- #
def fetch_automations(runner: OrcaRunner) -> list[dict[str, Any]]:
    raw = runner(["automations", "list", "--json"])
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise ConfiguratorError(
            f"orca automations list returned non-JSON output: {exc}"
        ) from exc
    if isinstance(parsed, dict):
        result = parsed.get("result")
        items = result.get("automations", []) if isinstance(result, dict) else []
    else:
        items = parsed if isinstance(parsed, list) else []
    return [a for a in items if isinstance(a, dict)]


def automation_repo_id(automation: dict[str, Any]) -> str | None:
    run_context = automation.get("runContext")
    context_repo_id = (
        run_context.get("repoId") if isinstance(run_context, dict) else None
    )
    repo = (
        context_repo_id
        or automation.get("projectId")
        or automation.get("repo")
        or automation.get("repoId")
    )
    if isinstance(repo, dict):
        rid = repo.get("id") or repo.get("repoId") or repo.get("uuid")
        return rid if isinstance(rid, str) else None
    if isinstance(repo, str):
        if repo.startswith("id:"):
            return repo[3:]
        return repo
    return None


def parse_marker(prompt: str | None) -> tuple[str, str] | None:
    if not isinstance(prompt, str):
        return None
    m = MARKER_RE.search(prompt)
    if not m:
        return None
    return m.group("repo"), m.group("reviewer")


def find_ours(
    automations: list[dict[str, Any]],
    name: str,
    github_repo: str,
    reviewer: str,
    repo_id: str,
) -> dict[str, Any] | None:
    """Return the single matching automation or raise on collision/mismatch."""
    same_name = [a for a in automations if a.get("name") == name]
    if not same_name:
        return None
    if len(same_name) > 1:
        raise ConfiguratorError(
            f"multiple automations share the deterministic name '{name}'; "
            "refusing to reconcile"
        )
    existing = same_name[0]
    parsed = parse_marker(existing.get("prompt"))
    if parsed != (github_repo, reviewer):
        raise ConfiguratorError(
            f"automation '{name}' exists but its marker identity does not match "
            f"{github_repo}/{reviewer}; name collision refused"
        )
    if automation_repo_id(existing) != repo_id:
        raise ConfiguratorError(
            f"automation '{name}' matches the marker but targets a different "
            "Orca repo; target identity mismatch refused"
        )
    return existing


# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #
def preflight_helper(helper_abs: Path) -> None:
    if not helper_abs.is_file():
        raise ConfiguratorError(
            f"sibling queue helper not found: {helper_abs}"
        )
    if not os.access(helper_abs, os.R_OK):
        raise ConfiguratorError(
            f"sibling queue helper is not readable: {helper_abs}"
        )
    if not os.access(helper_abs, os.X_OK):
        raise ConfiguratorError(
            f"sibling queue helper is not executable: {helper_abs}"
        )


# --------------------------------------------------------------------------- #
# Plan assembly
# --------------------------------------------------------------------------- #
class PlanSpec:
    __slots__ = (
        "github_repo", "reviewer", "name", "marker", "prompt", "precheck",
        "repo_id", "repo_path", "base_branch", "trigger", "provider",
        "timezone", "board_policy", "enabled", "helper_path",
        "cleanup_helper_path", "cleanup_command",
    )

    def __init__(self, **kw: Any) -> None:
        for k in self.__slots__:
            setattr(self, k, kw[k])

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


def build_plan(
    args: argparse.Namespace,
    runner: OrcaRunner,
) -> PlanSpec:
    github_repo = validate_github_repo(args.github_repo)
    reviewer = validate_reviewer(args.reviewer)
    validate_board_policy(args.board_policy)
    if args.trigger not in TRIGGERS:
        raise ConfiguratorError(f"--trigger must be one of {TRIGGERS}")

    repo = resolve_repo(args.repo_path, args.orca_repo, runner)
    verify_github_binding(repo, github_repo)
    base_branch = resolve_base_branch(repo, args.base_branch)
    provider = validate_provider(args.provider)
    timezone = validate_timezone(args.timezone)
    helper_abs = sibling_helper_path()
    preflight_helper(helper_abs)
    cleanup_abs = cleanup_helper_path()
    preflight_helper(cleanup_abs)
    repo_id_str = str(repo["id"])

    name = deterministic_name(github_repo, reviewer)
    cleanup_cmd = build_cleanup_command(
        cleanup_abs, name, github_repo, reviewer, repo_id_str
    )
    prompt = build_prompt(
        github_repo, reviewer, args.board_policy, base_branch,
        enable_hermes_critique=bool(args.hermes_critique),
        cleanup_command=cleanup_cmd,
    )
    precheck = build_precheck_command(helper_abs, github_repo, reviewer)

    return PlanSpec(
        github_repo=github_repo,
        reviewer=reviewer,
        name=name,
        marker=marker(github_repo, reviewer),
        prompt=prompt,
        precheck=precheck,
        repo_id=repo_id_str,
        repo_path=repo.get("path"),
        base_branch=base_branch,
        trigger=args.trigger,
        provider=provider,
        timezone=timezone,
        board_policy=args.board_policy,
        enabled=bool(args.enable),
        helper_path=str(helper_abs),
        cleanup_helper_path=str(cleanup_abs),
        cleanup_command=cleanup_cmd,
    )


def _emit_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def cmd_plan(args: argparse.Namespace, runner: OrcaRunner) -> int:
    spec = build_plan(args, runner)
    create_argv = build_create_argv(
        name=spec.name, prompt=spec.prompt, repo_id=spec.repo_id,
        trigger=spec.trigger, provider=spec.provider,
        base_branch=spec.base_branch, precheck=spec.precheck,
        timezone=spec.timezone, enabled=spec.enabled,
    )
    _emit_json({
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "command": "plan",
        "read_only": True,
        "spec": spec.to_dict(),
        "proposed_create_argv": create_argv,
        "default_disabled": not spec.enabled,
        "note": (
            "read-only plan; no Orca mutation performed. install creates or "
            "reconciles; default is disabled."
        ),
    })
    return 0


def cmd_status(args: argparse.Namespace, runner: OrcaRunner) -> int:
    github_repo = validate_github_repo(args.github_repo)
    reviewer = validate_reviewer(args.reviewer)
    repo = resolve_repo(args.repo_path, args.orca_repo, runner)
    verify_github_binding(repo, github_repo)
    name = deterministic_name(github_repo, reviewer)
    automations = fetch_automations(runner)
    same_name = [a for a in automations if a.get("name") == name]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "command": "status",
        "read_only": True,
        "name": name,
        "github_repo": github_repo,
        "reviewer": reviewer,
        "repo_id": repo["id"],
        "exists": False,
    }
    if not same_name:
        payload["state"] = "absent"
    elif len(same_name) > 1:
        payload["state"] = "ambiguous"
        payload["count"] = len(same_name)
    else:
        existing = same_name[0]
        parsed = parse_marker(existing.get("prompt"))
        payload["exists"] = True
        payload["state"] = "present"
        payload["automation_id"] = existing.get("id")
        payload["enabled"] = bool(existing.get("enabled", False))
        payload["marker_matches"] = parsed == (github_repo, reviewer)
        payload["repo_matches"] = automation_repo_id(existing) == str(repo["id"])
        payload["consistent"] = bool(
            payload["marker_matches"] and payload["repo_matches"]
        )
    _emit_json(payload)
    return 0


def cmd_install(args: argparse.Namespace, runner: OrcaRunner) -> int:
    spec = build_plan(args, runner)
    lock = SingleWriterLock(
        Path(args.lock_path) if args.lock_path else lock_path_default()
    )
    try:
        lock.acquire()
    except LockBusy as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 75
    try:
        automations = fetch_automations(runner)
        existing = find_ours(
            automations, spec.name, spec.github_repo, spec.reviewer, spec.repo_id
        )
        if existing is None:
            argv = build_create_argv(
                name=spec.name, prompt=spec.prompt, repo_id=spec.repo_id,
                trigger=spec.trigger, provider=spec.provider,
                base_branch=spec.base_branch, precheck=spec.precheck,
                timezone=spec.timezone, enabled=spec.enabled,
            )
            action = "create"
            before_id = None
        else:
            aid = existing.get("id")
            if not isinstance(aid, str) or not aid:
                raise ConfiguratorError(
                    "existing automation has no id; cannot edit"
                )
            argv = build_edit_argv(
                automation_id=aid, name=spec.name, prompt=spec.prompt,
                repo_id=spec.repo_id, trigger=spec.trigger,
                provider=spec.provider, base_branch=spec.base_branch,
                precheck=spec.precheck, timezone=spec.timezone,
                enabled=spec.enabled,
            )
            action = "edit"
            before_id = aid
        if not args.dry_run:
            runner(argv)
        _emit_json({
            "schema_version": SCHEMA_VERSION,
            "generated_at": _utc_now(),
            "command": "install",
            "action": action,
            "dry_run": bool(args.dry_run),
            "name": spec.name,
            "github_repo": spec.github_repo,
            "reviewer": spec.reviewer,
            "repo_id": spec.repo_id,
            "enabled": spec.enabled,
            "default_disabled": not spec.enabled,
            "existing_id": before_id,
            "argv": argv,
            "note": (
                "automation created/reconciled disabled unless --enable. "
                "Use a scheduled canary to validate precheck before enabling."
            ),
        })
        return 0
    finally:
        lock.release()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="configure-orca-pr-listener.py",
        description=(
            "Repo-agnostic Orca PR-listener configurator (disabled-first, "
            "explicit-only). plan/status are read-only; install creates or "
            "reconciles."
        ),
    )
    p.add_argument("--github-repo", required=True,
                   help="GitHub repo as OWNER/REPO")
    p.add_argument("--reviewer", required=True,
                   help="reviewer GitHub login")
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--repo-path",
                        help="absolute path of the Orca-registered repo")
    target.add_argument("--orca-repo",
                        help="Orca repo selector: id:<ID>, name:<NAME>, or path:<PATH>")
    p.add_argument("--base-branch", default=None,
                   help="base branch; default resolved Orca worktreeBaseRef")
    p.add_argument("--trigger", default="hourly",
                   help=f"schedule trigger (default hourly): {TRIGGERS}")
    p.add_argument("--provider", default="codex",
                   help="automation provider (default codex)")
    p.add_argument("--timezone", default=None,
                   help="optional schedule timezone")
    p.add_argument("--board-policy", default="required",
                   help=f"board policy (default required): {BOARD_POLICIES}")
    p.add_argument("--enable", action="store_true",
                   help="enable the automation (default: disabled)")
    p.add_argument("--hermes-critique", action="store_true",
                   help="include optional bounded Hermes critique in prompt")
    p.add_argument("--lock-path", default=None,
                   help="override single-writer lock path (testing)")
    p.add_argument("--dry-run", action="store_true",
                   help="resolve and build argv without invoking Orca mutation")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="read-only: print the deterministic plan")
    sub.add_parser("install", help="create or reconcile the automation")
    sub.add_parser("status", help="read-only: print current automation state")
    return p


def main(
    argv: list[str] | None = None,
    runner: OrcaRunner | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    orca_runner = runner or default_orca_runner
    try:
        if args.command == "plan":
            return cmd_plan(args, orca_runner)
        if args.command == "status":
            return cmd_status(args, orca_runner)
        if args.command == "install":
            return cmd_install(args, orca_runner)
    except ConfiguratorError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    except FileNotFoundError:
        sys.stderr.write("error: Orca CLI is not installed or not on PATH\n")
        return 127
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"error: Orca command failed with exit code {exc.returncode}\n")
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
