#!/usr/bin/env python3
"""Fail-closed post-result cleanup for Orca new-per-run PR-review workspaces.

This helper is the FINAL action an Orca PR-review automation runs, immediately
before emitting its private output. It resolves the exact current workspace,
validates the exact owning automation by deterministic name + marker identity +
Orca repo id, then starts a DETACHED watch subprocess that survives the run. The
watcher polls the exact automation's runs and removes ONLY the matching worktree
after a run with the exact ``workspaceId`` reaches status ``completed`` AND has a
non-empty ``outputSnapshot`` (i.e. Orca has persisted the run output).

Hard invariants (do not weaken):
  * Orca is invoked via ``subprocess`` argument arrays only, never through a
    shell. The detached watcher is spawned with an argv array,
    ``start_new_session=True``, a cwd OUTSIDE the workspace, and DEVNULL
    streams.
  * Deletion is fail-closed. On any validation failure, ambiguity, timeout, or
    error, the worktree is PRESERVED. No deletion ever happens for a run that is
    blocked, partial, stale, unposted, or lacks persisted output.
  * Identifiers are exact: no prefix, glob, or symlink trust. Before removal the
    exact worktree id is re-read and required to EQUAL the resolved full id, to
    target the SAME Orca repo id, and to report ``isMainWorktree`` false. The
    run must report the SAME exact ``workspaceId``.
  * No secrets, prompts, transcripts, env values, repo URLs, or branch SHAs are
    recorded. Only transient argv is handed to the detached child.
  * Orca owns scheduling, workspace/worktree lifecycle, and terminals. This
    helper only removes the single new-per-run worktree it validated; it does
    not create, schedule, or reconcile anything.

Commands:
  watch      Resolve current workspace, validate the automation, spawn the
             detached watcher, then exit 0. (Run inside the Orca workspace.)

Internal arm:
  --watch-arm ...   Detached polling loop invoked by ``watch``. Not for humans.

Exit codes (watch arm): 0 removed after validated completed run; 75 timed out
(worktree preserved); 2 validation/configuration error (preserved); 1 other
Orca/subprocess failure (preserved).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

# --------------------------------------------------------------------------- #
# Deterministic identity (kept byte-identical to configure-orca-pr-listener.py)
# --------------------------------------------------------------------------- #
MARKER_PREFIX = "[orca-pr-listener:v1"
MARKER_RE = re.compile(
    r"\[orca-pr-listener:v1 repo=(?P<repo>[^\s\]]+) reviewer=(?P<reviewer>[^\s\]]+)\]"
)
GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
GITHUB_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
NAME_SAFE_RE = re.compile(r"[^a-z0-9]+")
SELECTOR_RE = re.compile(r"^(?:id|name|path):.+$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

DEFAULT_WATCH_TIMEOUT = 3600
DEFAULT_POLL_INTERVAL = 30
MIN_TIMEOUT = 0
MIN_INTERVAL = 1


class CleanupError(RuntimeError):
    """Expected failure (bad input, ambiguity, validation). Exit code 2."""


# --------------------------------------------------------------------------- #
# Small helpers
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
# Validation
# --------------------------------------------------------------------------- #
def validate_github_repo(repo: str) -> str:
    if not isinstance(repo, str) or not GITHUB_REPO_RE.fullmatch(repo):
        raise CleanupError("--github-repo must be OWNER/REPO")
    return repo


def validate_reviewer(login: str) -> str:
    if not isinstance(login, str) or not GITHUB_LOGIN_RE.fullmatch(login):
        raise CleanupError("--reviewer must be a valid GitHub login")
    return login


def validate_orca_selector(selector: str) -> str:
    if not isinstance(selector, str) or not SELECTOR_RE.fullmatch(selector):
        raise CleanupError(
            "--orca-repo must be a selector like id:<ID>, name:<NAME>, path:<PATH>"
        )
    return selector


def validate_repo_id(repo_id: str) -> str:
    if not isinstance(repo_id, str) or not SAFE_ID_RE.fullmatch(repo_id):
        raise CleanupError("--repo-id must be a safe Orca repo identifier")
    return repo_id


def validate_worktree_id(worktree_id: str, repo_id: str) -> str:
    """Require Orca's full ``<repo-id>::<absolute-path>`` identity."""
    if not isinstance(worktree_id, str) or any(
        char in worktree_id for char in ("\x00", "\n", "\r")
    ):
        raise CleanupError("--worktree-id must be a safe full worktree id")
    prefix, separator, raw_path = worktree_id.partition("::")
    if separator != "::" or prefix != repo_id or not Path(raw_path).is_absolute():
        raise CleanupError(
            "--worktree-id must exactly match <repo-id>::<absolute-path>"
        )
    return worktree_id


def validate_timeout(value: int) -> int:
    if value < MIN_TIMEOUT:
        raise CleanupError("--watch-timeout must be >= 0")
    return value


def validate_interval(value: int) -> int:
    if value < MIN_INTERVAL:
        raise CleanupError("--poll-interval must be >= 1")
    return value


# --------------------------------------------------------------------------- #
# Orca runner (argument arrays; never shell)
# --------------------------------------------------------------------------- #
OrcaRunner = Callable[[list[str]], str]
PopenFn = Callable[..., Any]


def default_orca_runner(args: list[str]) -> str:
    """Run ``orca`` with an argument array, never through a shell."""
    proc = subprocess.run(
        ["orca", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def _default_popen(argv: list[str], **kwargs: Any) -> Any:
    return subprocess.Popen(argv, **kwargs)


# --------------------------------------------------------------------------- #
# JSON unwrapping (tolerates {"result": {...}} and bare shapes)
# --------------------------------------------------------------------------- #
def _result_list(parsed: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(parsed, dict):
        result = parsed.get("result")
        if isinstance(result, dict):
            items = result.get(key)
            return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []
        if isinstance(result, list):
            return [x for x in result if isinstance(x, dict)]
        items = parsed.get(key)
        return [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []
    return [x for x in parsed if isinstance(x, dict)] if isinstance(parsed, list) else []


def _result_object(parsed: Any, key: str | None = None) -> dict[str, Any]:
    if isinstance(parsed, dict):
        result = parsed.get("result")
        if isinstance(result, dict):
            if key is not None:
                nested = result.get(key)
                return nested if isinstance(nested, dict) else {}
            return result
        if key is not None:
            nested = parsed.get(key)
            return nested if isinstance(nested, dict) else {}
        return parsed
    return {}


# --------------------------------------------------------------------------- #
# Repo resolution (read-only; mirrors configure-orca-pr-listener.py)
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
        "githubRepo": github_repo,
    }


def fetch_repos(runner: OrcaRunner) -> list[dict[str, Any]]:
    raw = runner(["repo", "list", "--json"])
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise CleanupError(f"orca repo list returned non-JSON output: {exc}") from exc
    return [_canonical_repo(r) for r in _result_list(parsed, "repos")]


def resolve_repo(
    orca_selector: str | None, repo_id_override: str | None, runner: OrcaRunner
) -> dict[str, Any]:
    """Resolve exactly one Orca repo by selector or pre-resolved repo id."""
    if repo_id_override and orca_selector:
        raise CleanupError("provide --repo-id OR --orca-repo, not both")
    repos = fetch_repos(runner)
    if repo_id_override:
        validate_repo_id(repo_id_override)
        matches = [r for r in repos if r.get("id") == repo_id_override]
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
        raise CleanupError(
            f"no Orca repo matching: {orca_selector or 'id:' + repo_id_override!r}"
        )
    if len(matches) > 1:
        raise CleanupError(f"ambiguous Orca repo target: {len(matches)} matches")
    repo = matches[0]
    if not repo.get("id"):
        raise CleanupError("resolved Orca repo has no id; cannot target it")
    return repo


def verify_github_binding(repo: dict[str, Any], github_repo: str) -> None:
    registered = repo.get("githubRepo")
    if not isinstance(registered, str):
        raise CleanupError("resolved Orca repo has no verified GitHub remote identity")
    if registered.casefold() != github_repo.casefold():
        raise CleanupError(
            f"--github-repo does not match the Orca repo remote ({registered})"
        )


# --------------------------------------------------------------------------- #
# Automation matching (exact name + marker identity + repo id)
# --------------------------------------------------------------------------- #
def fetch_automations(runner: OrcaRunner) -> list[dict[str, Any]]:
    raw = runner(["automations", "list", "--json"])
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise CleanupError(
            f"orca automations list returned non-JSON output: {exc}"
        ) from exc
    return _result_list(parsed, "automations")


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
        return repo[3:] if repo.startswith("id:") else repo
    return None


def parse_marker(prompt: str | None) -> tuple[str, str] | None:
    if not isinstance(prompt, str):
        return None
    m = MARKER_RE.search(prompt)
    if not m:
        return None
    return m.group("repo"), m.group("reviewer")


def find_exact_automation(
    automations: list[dict[str, Any]],
    name: str,
    github_repo: str,
    reviewer: str,
    repo_id: str,
) -> dict[str, Any]:
    """Return the single exact automation or raise/preserve on mismatch.

    Exact-match policy: the deterministic name, the parsed marker identity, and
    the resolved repo id must all match exactly. Collisions and mismatches fail
    closed.
    """
    same_name = [a for a in automations if a.get("name") == name]
    if not same_name:
        raise CleanupError(f"no automation with the exact name '{name}'")
    if len(same_name) > 1:
        raise CleanupError(
            f"multiple automations share the exact name '{name}'; refuse to proceed"
        )
    existing = same_name[0]
    parsed = parse_marker(existing.get("prompt"))
    if parsed != (github_repo, reviewer):
        raise CleanupError(
            f"automation '{name}' marker identity does not match "
            f"{github_repo}/{reviewer}; refuse to proceed"
        )
    if automation_repo_id(existing) != repo_id:
        raise CleanupError(
            f"automation '{name}' targets a different Orca repo; refuse to proceed"
        )
    aid = existing.get("id")
    if not isinstance(aid, str) or not aid:
        raise CleanupError(f"automation '{name}' has no id; refuse to proceed")
    return existing


# --------------------------------------------------------------------------- #
# Worktree resolution and gating (exact identifiers)
# --------------------------------------------------------------------------- #
def fetch_current_worktree(runner: OrcaRunner) -> dict[str, Any]:
    raw = runner(["worktree", "current", "--json"])
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise CleanupError(
            f"orca worktree current returned non-JSON output: {exc}"
        ) from exc
    obj = _result_object(parsed, "worktree")
    if not obj:
        raise CleanupError("orca worktree current returned no worktree object")
    return obj


def fetch_worktree_by_id(
    runner: OrcaRunner, worktree_id: str
) -> dict[str, Any] | None:
    """Re-read the worktree; return the single exact-id match or None."""
    raw = runner(["worktree", "show", "--worktree", f"id:{worktree_id}", "--json"])
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise CleanupError(
            f"orca worktree show returned non-JSON output: {exc}"
        ) from exc
    worktree = _result_object(parsed, "worktree")
    return worktree if worktree.get("id") == worktree_id else None


def current_worktree_valid(wt: dict[str, Any], repo_id: str) -> None:
    """Gate the resolved current worktree before spawning the watcher."""
    wid = wt.get("id")
    if not isinstance(wid, str) or not wid.strip():
        raise CleanupError("current worktree has no full id; refuse to proceed")
    validate_worktree_id(wid, repo_id)
    if wt.get("repoId") != repo_id:
        raise CleanupError(
            "current worktree repo id does not match the automation repo; refuse"
        )
    if wt.get("isMainWorktree") is not False:
        raise CleanupError(
            "current worktree is the main worktree; refuse to remove it"
        )


def worktree_safe_for_removal(
    wt: dict[str, Any] | None, worktree_id: str, repo_id: str
) -> bool:
    """Removal-time gate: exact id equality, same repo, non-main worktree."""
    if not isinstance(wt, dict):
        return False
    if wt.get("id") != worktree_id:
        return False
    if wt.get("repoId") != repo_id:
        return False
    if wt.get("isMainWorktree") is not False:
        return False
    return True


# --------------------------------------------------------------------------- #
# Run polling (completed + non-empty persisted output only)
# --------------------------------------------------------------------------- #
def fetch_automation_runs(
    runner: OrcaRunner, automation_id: str
) -> list[dict[str, Any]]:
    raw = runner(["automations", "runs", "--id", automation_id, "--json"])
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise CleanupError(
            f"orca automations runs returned non-JSON output: {exc}"
        ) from exc
    return _result_list(parsed, "runs")


def _run_automation_id(run: dict[str, Any]) -> str | None:
    aid = run.get("automationId")
    if isinstance(aid, str):
        return aid
    auto = run.get("automation")
    if isinstance(auto, dict):
        v = auto.get("id")
        if isinstance(v, str):
            return v
    return None


def _non_empty_snapshot(snapshot: Any) -> bool:
    if isinstance(snapshot, str):
        return bool(snapshot.strip())
    if isinstance(snapshot, dict):
        content = snapshot.get("content")
        return isinstance(content, str) and bool(content.strip())
    return False


def match_completed_run(
    runs: list[dict[str, Any]],
    automation_id: str,
    worktree_id: str,
) -> dict[str, Any] | None:
    """Return the run that proves persisted completed output for our workspace."""
    for run in runs:
        if _run_automation_id(run) != automation_id:
            continue
        if run.get("workspaceId") != worktree_id:
            continue
        if run.get("status") != "completed":
            continue
        if not _non_empty_snapshot(run.get("outputSnapshot")):
            continue
        return run
    return None


# --------------------------------------------------------------------------- #
# Deletion (exact rm argv; never shell)
# --------------------------------------------------------------------------- #
def build_rm_argv(worktree_id: str) -> list[str]:
    return ["worktree", "rm", "--worktree", f"id:{worktree_id}", "--force", "--json"]


def choose_watcher_cwd(worktree_path: str | None) -> Path:
    """Pick a cwd OUTSIDE the workspace for the detached watcher."""
    home = Path(os.path.expanduser("~"))
    if worktree_path:
        try:
            wp = Path(worktree_path).resolve()
        except OSError:
            wp = None  # type: ignore[assignment]
        if wp is not None:
            try:
                home.resolve().relative_to(wp)
                return Path(os.sep)  # home is inside the worktree -> avoid it
            except ValueError:
                pass
    return home


def build_watch_arm_argv(
    script_abs: Path,
    *,
    automation_name: str,
    github_repo: str,
    reviewer: str,
    repo_id: str,
    worktree_id: str,
    watch_timeout: int,
    poll_interval: int,
) -> list[str]:
    return [
        sys.executable,
        str(script_abs),
        "--watch-arm",
        "--automation-name", automation_name,
        "--github-repo", github_repo,
        "--reviewer", reviewer,
        "--repo-id", repo_id,
        "--worktree-id", worktree_id,
        "--watch-timeout", str(watch_timeout),
        "--poll-interval", str(poll_interval),
    ]


def spawn_watcher(argv: list[str], cwd: Path, popen: PopenFn) -> Any:
    """Detach a watch subprocess: argv array, new session, DEVNULL, outside cwd."""
    return popen(
        argv,
        cwd=str(cwd),
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


# --------------------------------------------------------------------------- #
# Watch arm (detached polling loop)
# --------------------------------------------------------------------------- #
def run_watch_arm(
    *,
    runner: OrcaRunner,
    sleep: Callable[[float], None],
    automation_name: str,
    github_repo: str,
    reviewer: str,
    repo_id: str,
    worktree_id: str,
    watch_timeout: int,
    poll_interval: int,
) -> int:
    try:
        validate_github_repo(github_repo)
        validate_reviewer(reviewer)
        validate_repo_id(repo_id)
        validate_worktree_id(worktree_id, repo_id)
        if automation_name != deterministic_name(github_repo, reviewer):
            raise CleanupError("automation name does not match repo/reviewer")
        automations = fetch_automations(runner)
        auto = find_exact_automation(
            automations, automation_name, github_repo, reviewer, repo_id
        )
        automation_id = auto["id"]
        elapsed = 0.0
        while True:
            runs = fetch_automation_runs(runner, automation_id)
            run = match_completed_run(runs, automation_id, worktree_id)
            if run is not None:
                wt = fetch_worktree_by_id(runner, worktree_id)
                if not worktree_safe_for_removal(wt, worktree_id, repo_id):
                    return 2  # id/repo/main mismatch or gone -> preserve
                runner(build_rm_argv(worktree_id))
                return 0  # removed after validated completed, persisted run
            if elapsed >= watch_timeout:
                return 75  # timed out waiting -> preserve
            sleep(poll_interval)
            elapsed += poll_interval
    except CleanupError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    except FileNotFoundError:
        sys.stderr.write("error: Orca CLI is not installed or not on PATH\n")
        return 1
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(
            f"error: Orca command failed with exit code {exc.returncode}\n"
        )
        return 1


# --------------------------------------------------------------------------- #
# Public watch command
# --------------------------------------------------------------------------- #
def _emit_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def cmd_watch(
    args: argparse.Namespace,
    runner: OrcaRunner,
    popen: PopenFn,
) -> int:
    github_repo = validate_github_repo(args.github_repo)
    reviewer = validate_reviewer(args.reviewer)
    watch_timeout = validate_timeout(args.watch_timeout)
    poll_interval = validate_interval(args.poll_interval)

    repo = resolve_repo(args.orca_repo, args.repo_id, runner)
    repo_id = str(repo["id"])
    verify_github_binding(repo, github_repo)

    name = args.automation_name
    expected_name = deterministic_name(github_repo, reviewer)
    if name != expected_name:
        raise CleanupError(
            f"--automation-name '{name}' does not match the deterministic "
            f"name '{expected_name}' for {github_repo}/{reviewer}"
        )

    automations = fetch_automations(runner)
    find_exact_automation(automations, name, github_repo, reviewer, repo_id)

    wt = fetch_current_worktree(runner)
    current_worktree_valid(wt, repo_id)
    worktree_id = wt["id"]
    worktree_path = wt.get("path")
    watcher_cwd = choose_watcher_cwd(worktree_path if isinstance(worktree_path, str) else None)

    argv = build_watch_arm_argv(
        Path(__file__).resolve(),
        automation_name=name,
        github_repo=github_repo,
        reviewer=reviewer,
        repo_id=repo_id,
        worktree_id=worktree_id,
        watch_timeout=watch_timeout,
        poll_interval=poll_interval,
    )
    spawn_watcher(argv, watcher_cwd, popen)

    _emit_json({
        "schema": "orca-workspace-cleanup:watch:1",
        "armed": True,
        "note": "Detached fail-closed cleanup watcher started.",
    })
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_public_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="orca-automation-workspace-cleanup.py",
        description=(
            "Fail-closed post-result cleanup for Orca new-per-run PR-review "
            "workspaces. Validates the exact automation and current workspace, "
            "then spawns a detached watcher that removes the worktree only after "
            "Orca persists completed output."
        ),
    )
    p.add_argument("--automation-name", required=True,
                   help="deterministic automation name (must match repo/reviewer)")
    p.add_argument("--github-repo", required=True, help="GitHub repo as OWNER/REPO")
    p.add_argument("--reviewer", required=True, help="reviewer GitHub login")
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--orca-repo",
                        help="Orca repo selector: id:<ID>, name:<NAME>, or path:<PATH>")
    target.add_argument("--repo-id",
                        help="pre-resolved Orca repo id (exact)")
    p.add_argument("--watch-timeout", type=int, default=DEFAULT_WATCH_TIMEOUT,
                   help=f"watcher wait timeout in seconds (default {DEFAULT_WATCH_TIMEOUT})")
    p.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL,
                   help=f"run poll interval in seconds (default {DEFAULT_POLL_INTERVAL})")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("watch", help="resolve, validate, and spawn the detached watcher")
    return p


def build_watch_arm_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="orca-automation-workspace-cleanup.py --watch-arm")
    p.add_argument("--automation-name", required=True)
    p.add_argument("--github-repo", required=True)
    p.add_argument("--reviewer", required=True)
    p.add_argument("--repo-id", required=True)
    p.add_argument("--worktree-id", required=True)
    p.add_argument("--watch-timeout", type=int, required=True)
    p.add_argument("--poll-interval", type=int, required=True)
    return p


def main(
    argv: list[str] | None = None,
    runner: OrcaRunner | None = None,
    popen: PopenFn | None = None,
    sleep: Callable[[float], None] | None = None,
) -> int:
    if argv is None:
        argv = sys.argv[1:]
    orca_runner = runner or default_orca_runner
    popen_func = popen or _default_popen
    sleep_func = sleep or time.sleep
    try:
        if argv and argv[0] == "--watch-arm":
            args = build_watch_arm_parser().parse_args(argv[1:])
            return run_watch_arm(
                runner=orca_runner, sleep=sleep_func,
                automation_name=args.automation_name,
                github_repo=args.github_repo, reviewer=args.reviewer,
                repo_id=args.repo_id, worktree_id=args.worktree_id,
                watch_timeout=args.watch_timeout, poll_interval=args.poll_interval,
            )
        args = build_public_parser().parse_args(argv)
        if args.command == "watch":
            return cmd_watch(args, orca_runner, popen_func)
    except CleanupError as exc:
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
