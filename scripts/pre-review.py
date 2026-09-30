#!/usr/bin/env python3
"""Run the repository's available deterministic checks and emit a bounded packet."""

from __future__ import annotations

import argparse
import ast
import atexit
import hashlib
import json
import os
import re
import signal
import shutil
import shlex
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any


PACKET_BUDGET = 64 * 1024
OUTPUT_TAIL_BUDGET = 4 * 1024
DEFAULT_BASE = "origin/main"
DEFAULT_CHECK_TIMEOUT_SECONDS = 120
FOCUSED_PYTHON_CASE_TIMEOUT_SECONDS = 10
FOCUSED_PYTHON_FILE_TIMEOUT_SECONDS = 600
FOCUSED_PYTHON_DISPATCH_GRACE_SECONDS = 120
MIN_FREE_BYTES = 20 * 1024**3
TYPESCRIPT_SUFFIXES = {".ts", ".tsx", ".mts", ".cts"}
JAVASCRIPT_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs"}
BUILTIN_RULE_IDS = [
    "pre_review.url_parser_mismatch",
    "pre_review.github_token_permissions",
    "pre_review.external_response_shape",
    "pre_review.python_unicode_digits",
    "pre_review.no_floating_promises",
    "pre_review.identity_label_normalization",
    "pre_review.remote_database_seed_target_guard",
    "pre_review.legacy_identity_hostname_guard",
    "pre_review.workflow_gh_run_permissions",
    "pre_review.cited_symbol_exists",
    "pre_review.markdown_glob_code_span",
    "pre_review.plan_rewalk_unresolved_conflict",
]
STUDY_STATIC_DEFECT_RULES = {
    "12": "pre_review.identity_label_normalization",
    "30": "pre_review.url_parser_mismatch",
    "31": "pre_review.remote_database_seed_target_guard",
    "33": "pre_review.legacy_identity_hostname_guard",
    "45": "pre_review.python_unicode_digits",
    "47": "pre_review.external_response_shape",
    "48": "pre_review.workflow_gh_run_permissions",
    "49": "pre_review.cited_symbol_exists",
    "51": "pre_review.no_floating_promises",
    "52": "pre_review.markdown_glob_code_span",
    "55": "pre_review.plan_rewalk_unresolved_conflict",
}
ENVIRONMENT_ERROR_PATTERNS = (
    re.compile(r"\b(?:EPERM|EACCES|EMFILE)\b", re.I),
    re.compile(r"(?:missing|required|not set|undefined)[^\n]{0,80}DATABASE_URL|DATABASE_URL[^\n]{0,120}(?:missing|required|not set|undefined|not a|invalid|cannot)", re.I),
    re.compile(r"refusing to provision[^\n]{0,120}DATABASE_URL", re.I),
    re.compile(r"\bno server\b|ECONNREFUSED|connection refused|could not connect|command not found|(?:was|is) not able to start|unable to start|operation not permitted", re.I),
    re.compile(r"cannot find (?:module|package)[^\n]{0,180}(?:@/prisma/client|node_modules|generated|\.prisma)", re.I),
)
def starter_rules_path() -> Path:
    installed = Path(__file__).resolve().parent.parent / "semgrep" / "pre-review.yml"
    if installed.is_file():
        return installed
    return Path(__file__).resolve().parents[1] / "skillsets" / "pr-review" / "semgrep" / "pre-review.yml"


class PreReviewError(Exception):
    """An unrecoverable pre-review setup error."""


def repo_command_environment(repo: Path, output_dir: Path | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    local_bins = repo / "node_modules" / ".bin"
    environment["PATH"] = str(local_bins) + os.pathsep + environment.get("PATH", "")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if output_dir:
        environment["TMPDIR"] = str(output_dir)
    return environment


def execution_plan(tracked_clean: bool, head_matches: bool, free_bytes: int) -> tuple[str, str | None]:
    if tracked_clean and head_matches:
        return "in-place", None
    if free_bytes < MIN_FREE_BYTES:
        gib = free_bytes / (1024**3)
        return "unverified", f"environment: disk {gib:.1f} GiB free is below 20 GiB; detached worktree hydration skipped"
    return "detached-worktree", None


def porcelain_result(before: bytes, after: bytes) -> dict[str, Any]:
    unchanged = before == after
    result = {"name": "source-porcelain-unchanged", "command": ["git", "status", "--porcelain"],
              "status": "pass" if unchanged else "fail", "exit_code": 0 if unchanged else 1,
              "output_tail": "source porcelain unchanged" if unchanged else "tier defect: source porcelain changed during pre-review",
              "duration_ms": 0}
    if not unchanged:
        result.update(error_kind="tier-defect", verification="failed")
    return result


def tracked_tree_clean(repo: Path) -> bool:
    result = run_capture(["git", "status", "--porcelain=v1", "--untracked-files=no"], repo)
    if result.returncode:
        raise PreReviewError("cannot inspect tracked working-tree status")
    return not result.stdout


def workspace_error(name: str, reason: str) -> dict[str, Any]:
    return {"name": name, "command": [], "status": "error", "exit_code": None,
            "verification": "unverified", "error_kind": "environment", "duration_ms": None,
            "output_tail": reason}


def add_detached_worktree(source_repo: Path, head_sha: str) -> tuple[Path | None, str | None, Any | None]:
    worktree_root = Path(tempfile.mkdtemp(prefix="pre-review-worktree-"))
    worktree = worktree_root / "repo"
    result = run_capture(["git", "worktree", "add", "--detach", str(worktree), head_sha],
                         source_repo, timeout=120)
    if result.returncode:
        shutil.rmtree(worktree_root, ignore_errors=True)
        return None, "environment: could not create detached review worktree: " + output_tail(result.stdout).strip(), None

    def cleanup() -> subprocess.CompletedProcess[bytes]:
        result = run_capture(["git", "worktree", "remove", str(worktree)], source_repo, timeout=120)
        if result.returncode:
            return result
        try:
            worktree_root.rmdir()
        except OSError:
            pass
        atexit.unregister(cleanup)
        return result

    atexit.register(cleanup)
    return worktree, None, cleanup


def hydrate_checkout(repo: Path, output_dir: Path) -> str | None:
    package, manager = package_metadata(repo)
    has_lockfile = any((repo / name).is_file() for name in
                       ("pnpm-lock.yaml", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock"))
    if not package or not has_lockfile:
        return None
    if shutil.disk_usage(repo).free < MIN_FREE_BYTES:
        gib = shutil.disk_usage(repo).free / (1024**3)
        return f"environment: disk {gib:.1f} GiB free is below 20 GiB; dependency hydration skipped"
    wt_deps = Path.home() / ".local" / "bin" / "wt-deps"
    if not wt_deps.is_file() or not os.access(wt_deps, os.X_OK):
        return "environment: ~/.local/bin/wt-deps is unavailable; dependency hydration skipped"
    result = run_capture([str(wt_deps), str(repo)], repo, timeout=1200,
                         env=repo_command_environment(repo, output_dir))
    if result.returncode:
        return "environment: wt-deps failed: " + output_tail(result.stdout).strip()

    scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
    if isinstance(scripts, dict) and isinstance(scripts.get("postinstall"), str):
        codegen = [manager, "run", "postinstall"] if manager else []
    else:
        dependencies = {}
        for key in ("dependencies", "devDependencies"):
            items = package.get(key, {})
            if isinstance(items, dict):
                dependencies.update(items)
        prisma = binary_path(repo, "prisma") if "prisma" in dependencies or "@prisma/client" in dependencies else None
        codegen = [prisma, "generate"] if prisma else []
    if not codegen:
        return None
    result = run_capture(codegen, repo, timeout=600,
                         env=repo_command_environment(repo, output_dir))
    if result.returncode:
        return "environment: declared code generation failed: " + output_tail(result.stdout).strip()
    return None


def run_capture(argv: list[str], cwd: Path, timeout: float = 30,
                env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    process = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               shell=False, env=env, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        output = error.output or b""
        if process.stdout:
            process.stdout.close()
        process.wait()
        raise subprocess.TimeoutExpired(argv, timeout, output=output or error.output) from error
    return subprocess.CompletedProcess(argv, process.returncode, output)


def output_tail(raw: bytes) -> str:
    return raw[-OUTPUT_TAIL_BUDGET:].decode("utf-8", errors="replace")


def environment_error(tail: str) -> bool:
    if any(pattern.search(tail) for pattern in ENVIRONMENT_ERROR_PATTERNS):
        return True
    for match in re.finditer(r"cannot find (?:module|package)\s+['\"]([^'\"]+)['\"]", tail, re.I):
        module = match.group(1)
        if module.startswith("@/prisma/client") or module.startswith("@/generated/"):
            return True
        if not module.startswith(("./", "../", "/", "@/")):
            return True
    return False


def command_paths(repo: Path, paths: list[str]) -> list[str]:
    return ["./" + path for path in paths]


def is_pre_review_fixture(path: str) -> bool:
    return Path(path).parts[:3] == ("scripts", "fixtures", "pre-review")


def git_output(repo: Path, *args: str) -> bytes:
    result = run_capture(["git", *args], repo)
    if result.returncode:
        raise PreReviewError(output_tail(result.stdout).strip() or f"git {' '.join(args)} failed")
    return result.stdout


def resolve_repo(start: Path) -> Path:
    result = run_capture(["git", "rev-parse", "--show-toplevel"], start)
    if result.returncode:
        raise PreReviewError("current directory is not inside a Git repository")
    return Path(os.fsdecode(result.stdout.strip())).resolve()


def resolve_base(repo: Path, requested: str | None, base_sha_override: str | None = None,
                 merge_base_override: str | None = None) -> tuple[str, str, str]:
    ref = requested or DEFAULT_BASE
    if bool(base_sha_override) != bool(merge_base_override):
        raise PreReviewError("--base-sha and --merge-base-sha must be supplied together")
    if base_sha_override and merge_base_override:
        base = run_capture(["git", "rev-parse", "--verify", f"{base_sha_override}^{{commit}}"], repo)
        merge = run_capture(["git", "rev-parse", "--verify", f"{merge_base_override}^{{commit}}"], repo)
        if base.returncode:
            raise PreReviewError("provided base SHA is not available as a commit object")
        if merge.returncode:
            raise PreReviewError("provided merge-base SHA is not available as a commit object")
        base_sha = os.fsdecode(base.stdout.strip())
        merge_sha = os.fsdecode(merge.stdout.strip())
        for ancestor, descendant, label in ((merge_sha, "HEAD", "HEAD"), (merge_sha, base_sha, "base")):
            result = run_capture(["git", "merge-base", "--is-ancestor", ancestor, descendant], repo)
            if result.returncode:
                raise PreReviewError(f"provided merge-base SHA is not an ancestor of {label}")
        return ref, base_sha, merge_sha
    resolved = run_capture(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], repo)
    if resolved.returncode:
        raise PreReviewError(f"base ref cannot be resolved to a commit: {ref}")
    base_sha = os.fsdecode(resolved.stdout.strip())
    merge = run_capture(["git", "merge-base", "HEAD", base_sha], repo)
    if merge.returncode:
        raise PreReviewError(f"merge-base cannot be resolved for HEAD and {ref}")
    return ref, base_sha, os.fsdecode(merge.stdout.strip())


def nul_paths(raw: bytes) -> set[str]:
    return {os.fsdecode(part) for part in raw.split(b"\0") if part}


def changed_paths(repo: Path, merge_base: str, output_dir: Path, *,
                  include_worktree: bool = True) -> tuple[list[str], bool, int, list[str]]:
    committed = git_output(repo, "diff", "--name-only", "-z", f"{merge_base}..HEAD")
    working = git_output(repo, "diff", "--name-only", "-z", "HEAD", "--")
    untracked = git_output(repo, "ls-files", "--others", "--exclude-standard", "-z")
    excluded = None
    try:
        excluded = output_dir.resolve().relative_to(repo).as_posix()
    except ValueError:
        pass
    def included(path: str) -> bool:
        return not excluded or (path != excluded and not path.startswith(excluded.rstrip("/") + "/"))
    status = git_output(repo, "status", "--porcelain=v1", "--untracked-files=all", "-z")
    status_entries = [part for part in status.split(b"\0") if part]
    dirty = False
    index = 0
    while index < len(status_entries):
        entry = status_entries[index]
        path = os.fsdecode(entry[3:])
        if included(path):
            dirty = True
        if entry[:2] in {b"R ", b" C", b"RC", b" R", b"C ", b" C"}:
            index += 1
        index += 1
    committed_paths = nul_paths(committed)
    working_paths = nul_paths(working) | nul_paths(untracked)
    review_paths = committed_paths | working_paths if include_worktree else committed_paths
    paths = sorted(path for path in review_paths if included(path))
    excluded_worktree_paths = sorted(path for path in working_paths - committed_paths if included(path))
    committed_diff = git_output(repo, "diff", "--binary", f"{merge_base}..HEAD", "--")
    if not include_worktree:
        return paths, dirty, len(committed_diff), excluded_worktree_paths
    working_diff = git_output(repo, "diff", "--binary", "HEAD", "--")
    untracked_diff_bytes = 0
    for rel in nul_paths(untracked):
        if not included(rel):
            continue
        diff = run_capture(["git", "diff", "--no-index", "--binary", "--", os.devnull,
                            str((repo / rel).resolve())], repo)
        # git diff --no-index returns 1 when it found the expected new-file diff.
        if diff.returncode not in {0, 1}:
            raise PreReviewError(f"cannot measure untracked file diff: {rel}")
        untracked_diff_bytes += len(diff.stdout)
    return paths, dirty, len(committed_diff) + len(working_diff) + untracked_diff_bytes, []


def lint_reported_paths(output: str) -> list[str]:
    pattern = re.compile(
        r"^\s*(?:\[warn\]\s+)?(?P<path>(?:\./)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.[A-Za-z0-9_-]+)"
        r"(?::\d+(?::\d+)?|\(\d+(?:,\d+)?\))?(?:\s|$)"
    )
    paths = set()
    for line in output.splitlines():
        match = pattern.match(line)
        if match:
            path = match.group("path").removeprefix("./")
            paths.add(path)
    return sorted(paths)


def classify_outside_diff_lint(command: dict[str, Any], changed: list[str]) -> dict[str, Any]:
    if command["status"] != "fail":
        command.pop("_raw_output", None)
        return command
    reported = lint_reported_paths(command.get("_raw_output", command["output_tail"]))
    changed_set = {path.removeprefix("./") for path in changed}
    if not reported or any(path in changed_set for path in reported):
        command.pop("_raw_output", None)
        return command
    command["status"] = "outside_diff"
    command["outside_diff_paths"] = reported
    command["output_tail"] = (
        command["output_tail"] + f"\nout-of-diff issues: {len(reported)} file(s): " + ", ".join(reported)
    )
    command.pop("_raw_output", None)
    return command


def binary_path(repo: Path, name: str) -> str | None:
    local = repo / "node_modules" / ".bin" / name
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return shutil.which(name)


def record_command(name: str, argv: list[str], repo: Path, *, timeout: float = DEFAULT_CHECK_TIMEOUT_SECONDS,
                   timeout_scale: float = 1.0, skip_reason: str | None = None,
                   output_dir: Path | None = None,
                   unavailable_reason: str | None = None) -> dict[str, Any]:
    command = {"name": name, "command": argv, "status": "not-run", "exit_code": None,
               "output_tail": "", "duration_ms": None}
    if skip_reason:
        command.update(status="skip", output_tail=skip_reason)
        return command
    if unavailable_reason:
        return workspace_error(name, unavailable_reason)
    started = time.monotonic()
    try:
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
        environment = repo_command_environment(repo, output_dir)
        if name == "focused-playwright-tests" and output_dir:
            environment["PLAYWRIGHT_JSON_OUTPUT_FILE"] = str(output_dir / "playwright-report.json")
        result = run_capture(argv, repo, timeout=timeout * timeout_scale,
                             env=environment)
        tail = output_tail(result.stdout).replace(str(repo), "<repo>")
        is_environment_error = result.returncode != 0 and environment_error(tail)
        command.update(status="error" if is_environment_error else ("pass" if result.returncode == 0 else "fail"),
                       exit_code=result.returncode, output_tail=tail,
                       duration_ms=round((time.monotonic() - started) * 1000))
        if name == "repo-lint":
            command["_raw_output"] = result.stdout.decode("utf-8", "replace")
        if is_environment_error:
            command.update(verification="unverified", error_kind="environment",
                           output_tail=(tail + "\nenvironment error; result is unverified").strip())
    except FileNotFoundError:
        command.update(status="skip", output_tail="not installed")
    except subprocess.TimeoutExpired as error:
        raw = error.stdout or b""
        if isinstance(raw, str):
            raw = raw.encode("utf-8", errors="replace")
        command.update(status="timeout", verification="unverified",
                       output_tail=(output_tail(raw) + "\ncommand timed out; result is unverified").strip(),
                       duration_ms=round((time.monotonic() - started) * 1000))
    return command


def package_metadata(repo: Path) -> tuple[dict[str, Any], str | None]:
    package_file = repo / "package.json"
    if not package_file.is_file():
        return {}, None
    try:
        package = json.loads(package_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, None
    manager = "pnpm" if (repo / "pnpm-lock.yaml").exists() else (
        "yarn" if (repo / "yarn.lock").exists() else "npm")
    return package, manager


def package_script(package: dict[str, Any], manager: str | None, candidates: tuple[str, ...]) -> list[str] | None:
    scripts = package.get("scripts", {})
    if not manager or not isinstance(scripts, dict):
        return None
    for name in candidates:
        if isinstance(scripts.get(name), str):
            return [manager, "run", name]
    return None


def readonly_typecheck_command(repo: Path, package: dict[str, Any], manager: str | None) -> list[str] | None:
    scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
    if not manager or not isinstance(scripts, dict):
        return None
    name = next((candidate for candidate in ("typecheck", "type-check", "check:types")
                 if isinstance(scripts.get(candidate), str)), None)
    if not name:
        return None
    raw = scripts[name]
    try:
        tokens = shlex.split(raw)
    except ValueError:
        return [manager, "run", name]
    prefixes = (("tsc",), ("pnpm", "exec", "tsc"), ("npx", "--no-install", "tsc"))
    prefix = next((candidate for candidate in prefixes if tuple(tokens[:len(candidate)]) == candidate), None)
    if not prefix or any(token in {"&&", "||", ";", "|"} for token in tokens):
        return [manager, "run", name]
    tsc = binary_path(repo, "tsc")
    if not tsc:
        return [manager, "run", name]
    args = tokens[len(prefix):]
    filtered: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token in {"--incremental", "--tsBuildInfoFile"}:
            if token == "--tsBuildInfoFile" or (index + 1 < len(args) and args[index + 1] in {"true", "false"}):
                index += 1
            if token == "--tsBuildInfoFile" and index + 1 < len(args):
                index += 1
            index += 1
            continue
        if token.startswith("--incremental=") or token.startswith("--tsBuildInfoFile="):
            index += 1
            continue
        filtered.append(token)
        index += 1
    if "--noEmit" not in filtered:
        filtered.append("--noEmit")
    return [tsc, *filtered, "--incremental", "false"]


def has_mypy_config(repo: Path) -> bool:
    if any((repo / filename).is_file() for filename in ("mypy.ini", ".mypy.ini", "setup.cfg")):
        return True
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        try:
            return "[tool.mypy]" in pyproject.read_text(encoding="utf-8")
        except OSError:
            return False
    return False


def test_stem(path: Path) -> str:
    stem = path.stem.lower().replace("-", "_")
    stem = re.sub(r"[._](?:test|spec)$", "", stem)
    return stem[5:] if stem.startswith("test_") else stem


# test_*.py and test*.js style, Python's *_test.py, and JS/TS *.test.* / *.spec.*.
TEST_PATH_RE = re.compile(r"(?:^|/)(?:test[^/]*|[^/]*_test\.py|[^/]*\.(?:test|spec)\.[^.]+)$")


def related_test_paths(repo: Path, paths: list[str]) -> list[str]:
    changed = {Path(path) for path in paths}
    tests = {path for path in paths if TEST_PATH_RE.search(path)}
    source_stems = {test_stem(path) for path in changed if path.suffix in ({".py"} | TYPESCRIPT_SUFFIXES | JAVASCRIPT_SUFFIXES)}
    tracked_paths = nul_paths(git_output(repo, "ls-files", "-z"))
    candidates = tracked_paths | set(paths)
    ignored_parts = {".git", "node_modules", ".venv", "venv", "dist", "build", "coverage"}
    for rel in candidates:
        if any(part in ignored_parts for part in Path(rel).parts):
            continue
        candidate = Path(rel)
        if TEST_PATH_RE.search(rel) and test_stem(candidate) in source_stems:
            tests.add(rel)
    return sorted(tests)


def focused_test_commands(repo: Path, tests: list[str], output_dir: Path,
                          skip_tests: bool = False,
                          timeout_scale: float = 1.0) -> list[tuple[str, list[str], str | None]]:
    if skip_tests:
        return [("focused-tests", [], "skipped by --skip-tests; test commands were not run")]
    if not tests:
        return [("focused-tests", [], "no related test files changed or found")]
    python_tests = [path for path in tests if path.endswith(".py")]
    js_tests = [path for path in tests if Path(path).suffix in JAVASCRIPT_SUFFIXES]
    ts_tests = [path for path in tests if Path(path).suffix in TYPESCRIPT_SUFFIXES]
    commands: list[tuple[str, list[str], str | None]] = []
    absolute_python = command_paths(repo, python_tests)
    absolute_js = command_paths(repo, js_tests)
    absolute_ts = command_paths(repo, ts_tests)
    if python_tests:
        standalone_unittest = all(
            "unittest.main(" in (repo / path).read_text(encoding="utf-8", errors="replace")
            for path in python_tests
        )
        pytest = binary_path(repo, "pytest")
        if standalone_unittest:
            if len(absolute_python) == 1:
                command = [sys.executable, *absolute_python]
            else:
                runner = (
                    "import os, signal, subprocess, sys\n"
                    "timeout = float(sys.argv[1])\n"
                    "failed = False\n"
                    "for path in sys.argv[2:]:\n"
                    "    process = subprocess.Popen([sys.executable, path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)\n"
                    "    try:\n"
                    "        output, _ = process.communicate(timeout=timeout)\n"
                    "    except subprocess.TimeoutExpired as error:\n"
                    "        try:\n"
                    "            os.killpg(process.pid, signal.SIGKILL)\n"
                    "        except (ProcessLookupError, PermissionError):\n"
                    "            pass\n"
                    "        output = error.output or b''\n"
                    "        if process.stdout:\n"
                    "            process.stdout.close()\n"
                    "        process.wait()\n"
                    "        sys.stdout.buffer.write(output)\n"
                    "        sys.stdout.buffer.flush()\n"
                    "        print(f'{path} timed out after {timeout:g} seconds', file=sys.stderr)\n"
                    "        failed = True\n"
                    "        continue\n"
                    "    sys.stdout.buffer.write(output or b'')\n"
                    "    sys.stdout.buffer.flush()\n"
                    "    failed = failed or process.returncode != 0\n"
                    "raise SystemExit(1 if failed else 0)\n"
                )
                command = [sys.executable, "-c", runner,
                           str(FOCUSED_PYTHON_FILE_TIMEOUT_SECONDS * timeout_scale), *absolute_python]
            commands.append(("focused-python-tests", command, None))
        elif pytest:
            commands.append(("focused-python-tests", [pytest, *absolute_python], None))
        else:
            commands.append(("focused-python-tests", [], "pytest not installed; test files are not standalone unittest scripts"))
    if js_tests:
        node = shutil.which("node")
        commands.append(("focused-node-tests", [node, "--test", *absolute_js] if node else [],
                         None if node else "node not installed"))
    if ts_tests:
        playwright_tests = [path for path in ts_tests if path.startswith("e2e/") and path.endswith(".spec.ts")]
        remaining_ts_tests = [path for path in ts_tests if path not in playwright_tests]
        if playwright_tests:
            playwright = binary_path(repo, "playwright")
            config = repo / "playwright.config.ts"
            playwright_output = output_dir / "playwright-test-results"
            command = [playwright, "test", "--config", str(config), "--output", str(playwright_output),
                       "--reporter=json",
                       *command_paths(repo, playwright_tests)] if playwright and config.is_file() else []
            reason = None if command else ("playwright not installed" if not playwright else "playwright.config.ts not found")
            commands.append(("focused-playwright-tests", command, reason))
        if not remaining_ts_tests:
            return commands
        absolute_ts = command_paths(repo, remaining_ts_tests)
        package, _manager = package_metadata(repo)
        scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
        if isinstance(scripts, dict) and isinstance(scripts.get("test"), str) and "vitest" in scripts["test"]:
            vitest = binary_path(repo, "vitest")
            commands.append(("focused-typescript-tests", [vitest, "run", *absolute_ts] if vitest else [],
                             None if vitest else "vitest not installed"))
        elif isinstance(scripts, dict) and isinstance(scripts.get("test"), str) and "jest" in scripts["test"]:
            jest = binary_path(repo, "jest")
            commands.append(("focused-typescript-tests", [jest, "--runInBand", *absolute_ts] if jest else [],
                             None if jest else "jest not installed"))
        else:
            commands.append(("focused-typescript-tests", [], "no configured focused TypeScript test runner"))
    return commands


def focused_python_test_timeout(repo: Path, tests: list[str]) -> int:
    """Give each standalone unittest script a ten-minute slice."""
    case_count = 0
    standalone_script_count = 0
    other_test_file_count = 0
    for path in tests:
        try:
            source = (repo / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return FOCUSED_PYTHON_FILE_TIMEOUT_SECONDS * max(len(tests), 1)
        if "unittest.main(" in source:
            standalone_script_count += 1
            continue
        other_test_file_count += 1
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            return FOCUSED_PYTHON_FILE_TIMEOUT_SECONDS * max(len(tests), 1)
        case_count += sum(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test")
            for node in ast.walk(tree)
        )
    other_file_budget = (max(DEFAULT_CHECK_TIMEOUT_SECONDS,
                             case_count * FOCUSED_PYTHON_CASE_TIMEOUT_SECONDS)
                         if other_test_file_count else 0)
    standalone_budget = standalone_script_count * FOCUSED_PYTHON_FILE_TIMEOUT_SECONDS
    dispatch_grace = (standalone_script_count * FOCUSED_PYTHON_DISPATCH_GRACE_SECONDS
                      if standalone_script_count > 1 else 0)
    return standalone_budget + dispatch_grace + other_file_budget or DEFAULT_CHECK_TIMEOUT_SECONDS


def python_digit_rule(path: str, source: str) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    imported_ascii_flags = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "re"
        for alias in node.names if alias.name in {"A", "ASCII"}
    }
    regex_module_names = {
        alias.asname or alias.name
        for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names if alias.name == "re"
    } | {"re"}

    def flag_is_ascii(node: ast.AST | None) -> bool:
        if node is None:
            return False
        for part in ast.walk(node):
            if (isinstance(part, ast.Attribute) and part.attr in {"A", "ASCII"}
                    and isinstance(part.value, ast.Name) and part.value.id in regex_module_names):
                return True
            if isinstance(part, ast.Name) and part.id in imported_ascii_flags:
                return True
        return False

    def validation_context(call: ast.AST) -> bool:
        names = [Path(path).stem]
        current = call
        while current in parents:
            current = parents[current]
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(current.name)
            elif isinstance(current, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                targets = current.targets if isinstance(current, ast.Assign) else [current.target]
                names.extend(ast.unparse(target) for target in targets)
        context = " ".join(re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower().replace("_", " ") for name in names)
        domain = re.search(r"\b(date|day|month|year|timestamp|id|sha(?:1|256|512)?|version)\b", context)
        validation = re.search(r"\b(valid(?:ate|ation|ated)?|accept(?:ed|ance)?|parse(?:d|r)?)\b", context)
        return bool(domain and validation)

    hits: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if (not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name)
                or func.value.id not in regex_module_names):
            continue
        if func.attr not in {"compile", "match", "fullmatch", "search"}:
            continue
        try:
            pattern = ast.literal_eval(node.args[0])
        except (ValueError, TypeError):
            continue
        if not isinstance(pattern, str) or r"\d" not in pattern:
            continue
        positional_flag = 1 if func.attr == "compile" else 2
        flags = node.args[positional_flag] if len(node.args) > positional_flag else None
        for keyword in node.keywords:
            if keyword.arg == "flags":
                flags = keyword.value
        anchored = func.attr in {"match", "fullmatch"} or bool(
            re.match(r"^(?:\\A|\^)", pattern) and re.search(r"(?:\\Z|\\z|\$)$", pattern)
        )
        if anchored and validation_context(node) and not flag_is_ascii(flags):
            hits.append({"rule_id": "pre_review.python_unicode_digits", "path": path,
                         "line": node.lineno, "message": r"anchored date/identifier validation uses \d without re.ASCII"})
    return hits


def regex_hit(rule_id: str, path: str, source: str, pattern: re.Pattern[str], message: str) -> list[dict[str, Any]]:
    return [{"rule_id": rule_id, "path": path,
             "line": source.count("\n", 0, match.start()) + 1, "message": message}
            for match in pattern.finditer(source)]


MARKDOWN_GLOB = re.compile(r"\b(?:e2e|qa|tests?|scripts|src)(?:/[A-Za-z0-9_.-]+)?\.(\*+)")
MARKDOWN_UNCERTAIN_GLOB = re.compile(r"(?<!`)\b(?:e2e|qa|tests?|scripts|src)(?:/[A-Za-z0-9_.-]+)?\.\*(?!`)")  # Preserve main's exact hits in uncertain Markdown regions.
MARKDOWN_LIST_ITEM = re.compile(r"([-*+]|(\d{1,9})[.)])( *)")
MARKDOWN_FENCE = re.compile(r"(`{3,}|~{3,})(.*)")
MARKDOWN_THEMATIC_BREAK = re.compile(r"([-*_])(?:[ \t]*\1){2,}[ \t]*$")
MARKDOWN_SETEXT_UNDERLINE = re.compile(r"(?:=+|-+)[ \t]*$")
MARKDOWN_ATX_HEADING = re.compile(r"#{1,6}(?:[ \t]|$)")
MARKDOWN_ASCII_PUNCTUATION = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
MARKDOWN_STAR_RUN = re.compile(r"\*+")
# Ordinary words that can end a sentence right before bold or italic prose closes.
MARKDOWN_PROSE_WORDS = {"test", "tests", "scripts"}


def markdown_expand_container_tabs(line: str) -> str:
    """Expand tabs among leading whitespace, blockquote and list markers to CommonMark's 4-column stops."""
    column = 0
    out: list[str] = []
    for index, char in enumerate(line):
        if char == "\t":
            out.append(" " * (4 - column % 4))
            column += 4 - column % 4
        elif char in " >-*+.)0123456789":
            out.append(char)
            column += 1
        else:
            return "".join(out) + line[index:]
    return "".join(out)


def markdown_indent(text: str) -> int:
    return len(text) - len(text.lstrip(" "))


def markdown_block_start(rest: str) -> bool:
    """True when a line (inside its containers) starts a block, so it cannot be a lazy paragraph line."""
    if not rest.strip():
        return True
    if markdown_indent(rest) >= 4:
        return False
    body = rest.lstrip(" ")
    item = MARKDOWN_LIST_ITEM.match(body)
    fence = MARKDOWN_FENCE.match(body)
    if fence and fence.group(1)[0] == "`" and "`" in fence.group(2):
        fence = None  # a backtick run followed by more backticks is a code span, not a fence
    return bool(body.startswith(">") or fence or MARKDOWN_THEMATIC_BREAK.match(body)
                or MARKDOWN_ATX_HEADING.match(body)
                or (item and (item.group(3) or not body[item.end():].strip())))  # an empty item too


def markdown_paragraphs(source: str) -> list[tuple[int, str, bool]]:
    """Return (first line number, text, uncertain) paragraphs following CommonMark containers.

    Blockquotes and list items form a container stack. Each line first matches the open containers,
    then may open new ones. A fenced block ends at its closing fence or when any enclosing container
    ends; a paragraph also continues lazily when a line matches too few containers. Indented lines
    after a container boundary are kept as uncertain regions so inline code cannot pair across them.
    """
    paragraphs: list[tuple[int, str, bool]] = []
    lines: list[str] = []
    start = 0
    uncertain_lines: list[str] = []
    uncertain_start = 0
    uncertain_depth = 0
    stack: list[int] = []  # 0 = blockquote; n > 0 = list item whose content starts n columns in
    fence: str | None = None
    fence_depth = 0

    def flush() -> None:
        nonlocal lines
        if lines:
            paragraphs.append((start, "\n".join(lines), False))
            lines = []

    def flush_uncertain() -> None:
        nonlocal uncertain_start, uncertain_lines
        if uncertain_lines:
            paragraphs.append((uncertain_start, "\n".join(uncertain_lines), True))
            uncertain_lines = []
            uncertain_start = 0

    for number, raw_line in enumerate(source.splitlines(), 1):
        closed_by_indent = False
        line = markdown_expand_container_tabs(raw_line)
        pos = matched = 0
        for width in stack:
            rest = line[pos:]
            if width == 0:
                offset = markdown_indent(rest)
                if offset < 4 and rest[offset:offset + 1] == ">":
                    pos += offset + 1 + (line[pos + offset + 1:pos + offset + 2] == " ")
                    matched += 1
                    continue
                break
            if not rest.strip():
                matched += 1
                continue
            if markdown_indent(rest) >= width:
                pos += width
                matched += 1
                continue
            break
        rest = line[pos:]
        if uncertain_lines:
            if rest.strip() and matched == uncertain_depth and markdown_indent(rest) >= 4:
                uncertain_lines.append(rest)
                continue
            flush_uncertain()
        if fence is not None:
            if matched >= fence_depth:
                closer = MARKDOWN_FENCE.match(rest.lstrip(" "))
                if closer and markdown_indent(rest) < 4 and closer.group(1)[0] == fence[0] \
                        and len(closer.group(1)) >= len(fence) and not closer.group(2).strip():
                    fence = None
                continue
            fence = None  # a fenced block also ends with its blockquote or list item
        if matched < len(stack):
            if lines and not markdown_block_start(rest):
                lines.append(rest)  # lazy continuation keeps the paragraph and its containers
                continue
            flush()
            closed_by_indent = matched < len(stack) and markdown_indent(rest) >= 4
            del stack[matched:]
        while markdown_indent(rest) < 4:  # open new containers
            offset = markdown_indent(rest)
            body = rest[offset:]
            if body.startswith(">"):
                flush()
                stack.append(0)
                step = offset + 1 + (body[1:2] == " ")
                pos, rest = pos + step, rest[step:]
                continue
            item = MARKDOWN_LIST_ITEM.match(body)
            if item and (item.group(3) or not body[item.end():]) and not MARKDOWN_THEMATIC_BREAK.match(body):
                content = body[item.end():]
                ordered_start = item.group(2)
                if lines and (not content.strip() or (ordered_start is not None and ordered_start != "1")):
                    break  # an empty or non-1 ordered item cannot interrupt a paragraph
                flush()
                marker_width = offset + len(item.group(1))
                spaces = len(item.group(3))
                width = marker_width + (1 if not content.strip() or spaces > 4 else spaces)
                stack.append(width)
                step = min(width, len(rest))
                pos, rest = pos + step, rest[step:]
                continue
            break
        if not rest.strip():
            flush()
            continue
        body = rest.lstrip(" ")
        marker = MARKDOWN_FENCE.match(body) if markdown_indent(rest) < 4 else None
        if marker and marker.group(1)[0] == "`" and "`" in marker.group(2):
            marker = None  # a backtick run followed by more backticks is a code span, not a fence
        if marker:
            flush()
            fence, fence_depth = marker.group(1), len(stack)
            continue
        if markdown_indent(rest) >= 4 and not lines:
            if closed_by_indent:
                flush()
                uncertain_start = number
                uncertain_lines.append(rest)
                uncertain_depth = len(stack)
            continue  # indented code, or an unmasked uncertain region after a container boundary
        if lines and matched == len(stack) and markdown_indent(rest) < 4 and MARKDOWN_SETEXT_UNDERLINE.match(body):
            flush()  # a setext underline makes the paragraph above a heading and ends it
            continue
        if markdown_indent(rest) < 4 and (MARKDOWN_THEMATIC_BREAK.match(body) or MARKDOWN_ATX_HEADING.match(body)):
            flush()
            if MARKDOWN_ATX_HEADING.match(body):
                paragraphs.append((number, body, False))
            continue
        if not lines:
            start = number
        lines.append(rest)
    flush()
    flush_uncertain()
    return paragraphs


def markdown_mask_inline_code(text: str) -> str:
    """Neutralise code-span contents and backslash escapes, scanning left to right as CommonMark does.

    Outside code, `\\` before ASCII punctuation makes that character literal (it can neither open a code
    span nor delimit emphasis), so both become `!`. A backtick run opens a code span only when a run of
    exactly the same length follows; inside the span backslashes are literal. The span's contents become
    letters and its backticks stay, so emphasis flanking next to the span matches the source. Newlines are kept.
    """
    out = list(text)
    index, size = 0, len(text)
    while index < size:
        char = text[index]
        if char == "\\" and index + 1 < size and text[index + 1] in MARKDOWN_ASCII_PUNCTUATION:
            out[index] = out[index + 1] = "!"
            index += 2
            continue
        if char != "`":
            index += 1
            continue
        run_end = index
        while run_end < size and text[run_end] == "`":
            run_end += 1
        length, cursor, close = run_end - index, run_end, -1
        while cursor < size:
            found = text.find("`" * length, cursor)
            if found < 0:
                break
            after = found
            while after < size and text[after] == "`":
                after += 1
            if after - found == length:
                close = found
                break
            cursor = after  # a longer or shorter run cannot close this span
        if close < 0:
            index = run_end  # an unmatched run is literal text
            continue
        for position in range(run_end, close):
            if out[position] != "\n":
                out[position] = "x"  # the span's backticks stay, so neighbouring `*` keep their flanking
        index = close + length
    return "".join(out)


def markdown_punctuation(char: str) -> bool:
    return unicodedata.category(char)[0] in "PS"


def markdown_star_closers(text: str) -> dict[int, tuple[int, list[int]]]:
    """Pair `*` delimiter runs as CommonMark does: flanking rules, the rule of three, nearest opener first.

    Returns, for each run that closes emphasis, (stars consumed as closers, content start offsets of the
    openers it closed).
    """
    openers: list[list[int]] = []  # [remaining stars, run length, can also close, content start]
    closers: dict[int, tuple[int, list[int]]] = {}
    for run in MARKDOWN_STAR_RUN.finditer(text):
        before = text[run.start() - 1] if run.start() else " "
        after = text[run.end()] if run.end() < len(text) else " "
        left = not after.isspace() and (not markdown_punctuation(after) or before.isspace()
                                        or markdown_punctuation(before))
        right = not before.isspace() and (not markdown_punctuation(before) or after.isspace()
                                          or markdown_punctuation(after))
        length = remaining = len(run.group(0))
        consumed, starts = 0, []
        while right and remaining and openers:
            for index in range(len(openers) - 1, -1, -1):
                _left, total, both, _start = openers[index]
                if not ((both or left) and (total + length) % 3 == 0 and (total % 3 or length % 3)):
                    break
            else:
                break
            del openers[index + 1:]  # delimiters between opener and closer can no longer match
            opener = openers[index]
            use = 2 if remaining >= 2 and opener[0] >= 2 else 1
            opener[0] -= use
            remaining -= use
            consumed += use
            starts.append(opener[3])
            if not opener[0]:
                openers.pop()
        if consumed:
            closers[run.start()] = (consumed, starts)
        if remaining and left:
            openers.append([remaining, length, int(right), run.end()])
    return closers


def markdown_glob_hits(path: str, source: str) -> list[dict[str, Any]]:
    # A glob star is lost whenever Markdown consumes it as emphasis: `*e2e.*` renders as italic
    # "e2e." and `**Use e2e.* files**` loses its star too. The only star that is not a glob is one
    # that exactly closes prose emphasis ending in an ordinary word ("**Four red tests.**").
    # Fenced blocks, indented code and code spans (which may span lines) are literal text.
    hits: list[dict[str, Any]] = []
    for first_line, paragraph, uncertain in markdown_paragraphs(source):
        if uncertain:
            for match in MARKDOWN_UNCERTAIN_GLOB.finditer(paragraph):
                hits.append({"rule_id": "pre_review.markdown_glob_code_span", "path": path,
                             "line": first_line + paragraph.count("\n", 0, match.start()),
                             "message": "glob-like token is emphasis text; wrap it in a Markdown code span"})
            continue
        text = markdown_mask_inline_code(paragraph)
        closers = markdown_star_closers(text)
        for match in MARKDOWN_GLOB.finditer(text):
            consumed, content_starts = closers.get(match.start(1), (0, []))
            word = text[match.start():match.start(1) - 1]
            # Links, autolinks and HTML can hide or add delimiters this scan does not model, so a span
            # containing them keeps the base rule's hit instead of trusting the pairing.
            span = text[min(content_starts, default=match.start()):match.start(1)]
            closes_prose = consumed == len(match.group(1)) and word in MARKDOWN_PROSE_WORDS \
                and match.start() not in content_starts and not any(char in span for char in "[]<>")
            if not closes_prose:
                hits.append({"rule_id": "pre_review.markdown_glob_code_span", "path": path,
                             "line": first_line + text.count("\n", 0, match.start()),
                             "message": "glob-like token is emphasis text; wrap it in a Markdown code span"})
    return hits


def external_response_shape_hits(path: str, source: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    # A dereference caught by a broad handler cannot escape with the wrong shape.
    # Keep this AST check Python-only; the companion checks remain readable regexes.
    protected_offsets: set[int] = set()
    protected_lines: set[int] = set()
    if Path(path).suffix.lower() == ".py":
        try:
            tree = ast.parse(source)
        except SyntaxError:
            tree = None
        if tree is not None:
            parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
            lines = source.splitlines(keepends=True)
            line_starts: list[int] = []
            cursor = 0
            for line in lines:
                line_starts.append(cursor)
                cursor += len(line)

            def node_offset(node: ast.AST) -> int:
                line = lines[node.lineno - 1]  # type: ignore[attr-defined]
                char_column = len(line.encode("utf-8")[:node.col_offset].decode("utf-8"))  # type: ignore[attr-defined]
                return line_starts[node.lineno - 1] + char_column

            def catches_shape_error(handler: ast.ExceptHandler) -> bool:
                if handler.type is None:
                    return True
                names = {node.id for node in ast.walk(handler.type) if isinstance(node, ast.Name)}
                return bool(names & {"Exception", "BaseException", "AttributeError", "TypeError"})

            for node in ast.walk(tree):
                if not isinstance(node, (ast.Call, ast.Attribute)):
                    continue
                current: ast.AST = node
                while current in parents:
                    parent = parents[current]
                    if isinstance(parent, ast.Try):
                        if current in parent.body and any(catches_shape_error(handler) for handler in parent.handlers):
                            protected_offsets.add(node_offset(node))
                            for statement in parent.body:
                                protected_lines.update(range(statement.lineno, statement.end_lineno + 1))
                        break
                    current = parent
    # Defect #47: an external JSON object is dereferenced before its shape is checked.
    assignment = re.compile(
        r"(?m)^\s*(?P<name>[A-Za-z_]\w*)\s*=\s*requests\.[A-Za-z_]\w*\([^\n]*\)\.json\(\)"
    )
    attribute_template = r"\b{0}\s*\.\s*([A-Za-z_]\w*)"
    guard_template = r"\bisinstance\s*\(\s*{0}\s*,\s*(?:dict|Mapping)\s*\)|\bvalidate\s*\(\s*{0}\b"
    for match in assignment.finditer(source):
        name = match.group("name")
        # Restrict the plain regex to this function-sized window to avoid unrelated guards.
        function_end = re.search(r"(?m)^\s*(?:async\s+)?def\s+\w+|^\s*class\s+\w+", source[match.end():])
        end = match.end() + function_end.start() if function_end else len(source)
        window = source[match.end():end]
        escaped = re.escape(name)
        access = re.search(attribute_template.format(escaped), window)
        absolute_access = match.end() + access.start() if access else -1
        access_line = source.count("\n", 0, absolute_access) + 1
        if (access and absolute_access not in protected_offsets and access_line not in protected_lines
                and not re.search(guard_template.format(escaped), window[:access.start()])):
            line = source.count("\n", 0, match.start()) + 1
            hits.append({"rule_id": "pre_review.external_response_shape", "path": path,
                         "line": line, "message": f"external JSON response {name} is accessed before a shape guard"})
    # Defect #47: direct `.get` on JSON read from the gate's external evidence reader is unguarded.
    external_body = re.compile(r"(?m)^\s*(?P<name>[A-Za-z_]\w*)\s*=\s*rd\[\s*[\"']read[\"']\s*\]\s*\(")
    for body_match in external_body.finditer(source):
        name = re.escape(body_match.group("name"))
        direct = re.search(rf"json\.loads\s*\(\s*{name}\s*\)\s*\.\s*(?:get|items|keys|values)\s*\(", source[body_match.end():])
        if direct:
            absolute = body_match.end() + direct.start()
            if absolute in protected_offsets or source.count("\n", 0, absolute) + 1 in protected_lines:
                continue
            hits.append({"rule_id": "pre_review.external_response_shape", "path": path,
                         "line": source.count("\n", 0, absolute) + 1,
                         "message": "external evidence JSON is dereferenced before a dict/schema check"})
    return hits


def inline_yaml_quote_starts(prefix: str) -> bool:
    """A quote opens a scalar only at a key/value boundary, not inside plain text."""
    segment = re.split(r"[,{\[]", prefix)[-1].strip()
    return not segment or (segment.endswith(":") and segment.count(":") == 1)


def inline_yaml_map_body(value: str) -> str | None:
    if not value.startswith("{"):
        return None
    quote: str | None = None
    escaped = False
    depth = 0
    for index, char in enumerate(value):
        if quote:
            if quote == '"':
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
            elif escaped:
                escaped = False
            elif char == "'" and index + 1 < len(value) and value[index + 1] == "'":
                escaped = True
            elif char == quote:
                quote = None
            continue
        prefix = value[:index]
        if char in {"'", '"'} and inline_yaml_quote_starts(prefix):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return value[1:index]
    return None


def strip_yaml_comments(value: str) -> str:
    """Remove YAML comments outside quoted scalars, preserving quote state across lines."""
    quote: str | None = None
    escaped = False
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if quote == '"':
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif quote == "'":
            if escaped:
                escaped = False
            elif char == "'" and index + 1 < len(value) and value[index + 1] == "'":
                escaped = True
            elif char == quote:
                quote = None
        elif char in {"'", '"'} and inline_yaml_quote_starts(value[:index]):
            quote = char
        elif char == "#" and (index == 0 or value[index - 1].isspace()):
            while index < len(value) and value[index] != "\n":
                index += 1
            continue
        result.append(char)
        index += 1
    return "".join(result)


def inline_yaml_map_value(value: str, lines: list[str], index: int, end: int) -> tuple[str, int]:
    """Join a flow map continued on indented lines; return its value and next line."""
    value = strip_yaml_comments(value)
    stop = index + 1
    while value.startswith("{") and inline_yaml_map_body(value) is None and stop < end:
        value += "\n" + lines[stop].strip()
        value = strip_yaml_comments(value)
        stop += 1
    return value, stop


def inline_yaml_map_entries(body: str) -> list[tuple[str, str]]:
    entries: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    depth = 0
    for index, char in enumerate(body):
        if quote:
            if quote == '"':
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
            elif escaped:
                escaped = False
            elif char == "'" and index + 1 < len(body) and body[index + 1] == "'":
                escaped = True
            elif char == quote:
                quote = None
            continue
        prefix = body[start:index]
        if char in {"'", '"'} and inline_yaml_quote_starts(prefix):
            quote = char
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            entries.append(body[start:index])
            start = index + 1
    entries.append(body[start:])

    result: list[tuple[str, str]] = []
    for entry in entries:
        quote = None
        escaped = False
        for index, char in enumerate(entry):
            if quote:
                if quote == '"':
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == quote:
                        quote = None
                elif escaped:
                    escaped = False
                elif char == "'" and index + 1 < len(entry) and entry[index + 1] == "'":
                    escaped = True
                elif char == quote:
                    quote = None
            elif char in {"'", '"'} and inline_yaml_quote_starts(entry[:index]):
                quote = char
            elif char == ":":
                key = entry[:index].strip()
                if len(key) >= 2 and key[0] == key[-1] and key[0] in {"'", '"'}:
                    key = key[1:-1]
                result.append((key, entry[index + 1:].strip()))
                break
    return result


def effective_workflow_token(lines: list[str], env_blocks: tuple[tuple[int, int] | None, ...],
                             inline_envs: tuple[str, ...] = ()) -> bool:
    """Apply workflow/job/step env precedence and reject statically empty tokens."""
    values: dict[str, str] = {}
    def apply_inline(value: str) -> None:
        for name, raw_value in inline_yaml_map_entries(value):
            if name not in {"GH_TOKEN", "GITHUB_TOKEN"}:
                continue
            token_value = raw_value
            if len(token_value) >= 2 and token_value[0] == token_value[-1] and token_value[0] in {"'", '"'}:
                token_value = token_value[1:-1]
            values[name] = "" if token_value.lower() in {"", "null", "~"} else token_value

    for part in env_blocks:
        if not part:
            continue
        flow_map_continuations: set[int] = set()
        for index, line in enumerate(lines[part[0]:part[1]], part[0]):
            if index in flow_map_continuations:
                continue
            inline_mapping = re.match(
                r"^[ \t]*(?:-[ \t]*)?(?:env|'env'|\"env\")[ \t]*:[ \t]*(.*)$", line)
            if inline_mapping:
                inline_value, next_index = inline_yaml_map_value(
                    inline_mapping.group(1).strip(), lines, index, part[1])
                body = inline_yaml_map_body(inline_value)
                if body is not None:
                    apply_inline(body)
                    flow_map_continuations.update(range(index + 1, next_index))
            match = re.match(r"^[ \t]*(['\"]?(?:GH_TOKEN|GITHUB_TOKEN)['\"]?)[ \t]*:[ \t]*(.*)$", line)
            if not match:
                continue
            value = match.group(2).split(" #", 1)[0].strip()
            if re.fullmatch(r"[|>](?:[1-9][+-]?|[+-][1-9]?)?", value):
                scalar_indent = len(line) - len(line.lstrip(" \t"))
                block_lines = []
                for child in lines[index + 1:part[1]]:
                    if child.strip() and len(child) - len(child.lstrip(" \t")) <= scalar_indent:
                        break
                    block_lines.append(child.strip())
                value = "\n".join(block_lines).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            name = match.group(1).strip("'\"")
            values[name] = "" if value.lower() in {"", "null", "~"} else value
    for inline in inline_envs:
        apply_inline(inline)
    effective = values.get("GH_TOKEN", values.get("GITHUB_TOKEN", ""))
    return bool(effective)


def workflow_step_env(lines: list[str], step: tuple[int, int] | None, step_indent: int
                      ) -> tuple[tuple[int, int] | None, str]:
    if not step:
        return None, ""
    start, end = step
    inline_header = re.match(r"^[ \t]*-[ \t]*(?:env|'env'|\"env\")[ \t]*:[ \t]*(.*)$", lines[start])
    if inline_header:
        value = inline_header.group(1).strip()
        if value:
            value, stop = inline_yaml_map_value(value, lines, start, end)
            return (start, stop), value
        stop = start + 1
        while stop < end and (not lines[stop].strip() or lines[stop].lstrip().startswith("#") or
                              len(lines[stop]) - len(lines[stop].lstrip(" \t")) > step_indent + 2):
            stop += 1
        return (start + 1, stop), ""
    item_prefix = re.match(r"^[ \t]*-[ \t]+", lines[start])
    property_indent = item_prefix.end() if item_prefix else step_indent + 2
    for index in range(start + 1, end):
        line_indent = len(lines[index]) - len(lines[index].lstrip(" \t"))
        if line_indent == property_indent and yaml_key_header(lines[index], "env"):
            stop = index + 1
            while stop < end and (not lines[stop].strip() or lines[stop].lstrip().startswith("#") or
                                  len(lines[stop]) - len(lines[stop].lstrip(" \t")) > property_indent):
                stop += 1
            return (index, stop), ""
    return None, ""


def include_flow_map_close(lines: list[str], part: tuple[int, int] | None, boundary: int
                           ) -> tuple[int, int] | None:
    if not part:
        return part
    for index in range(part[0], part[1]):
        header = re.match(
            r"^[ \t]*(?:-[ \t]*)?(?:env|'env'|\"env\")[ \t]*:[ \t]*(.*)$", lines[index])
        if not header or not header.group(1).lstrip().startswith("{"):
            continue
        value, stop = inline_yaml_map_value(header.group(1).strip(), lines, index, boundary)
        if inline_yaml_map_body(value) is not None:
            return (part[0], max(part[1], stop))
    return part


def yaml_key_header(line: str, key: str) -> bool:
    quoted = rf"(?:{re.escape(key)}|'(?:{re.escape(key)})'|\"(?:{re.escape(key)})\")"
    return bool(re.match(rf"{quoted}[ \t]*:", line.strip()))


def yaml_mapping_key_header(line: str) -> bool:
    return bool(re.fullmatch(r"(?:[A-Za-z0-9_-]+|'[^']+'|\"[^\"]+\")[ \t]*:[ \t]*(?:#.*)?",
                             line.strip()))


def yaml_mapping_entry(line: str) -> bool:
    return bool(re.match(r"(?:[A-Za-z0-9_-]+|'[^']+'|\"[^\"]+\")[ \t]*:", line.strip()))


def mapping_child_indent(lines: list[str], start: int, end: int, parent_indent: int) -> int:
    for line in lines[start:end]:
        line_indent = len(line) - len(line.lstrip(" \t"))
        if (line.strip() and not line.lstrip().startswith(("#", "-"))
                and line_indent > parent_indent and yaml_mapping_entry(line)):
            return line_indent
    return parent_indent + 2


def yaml_env_flow_map_continuations(lines: list[str], start: int, end: int) -> set[int]:
    continuation_lines: set[int] = set()
    for index in range(start, end):
        header = re.match(r"^[ \t]*(?:-[ \t]*)?(?:env|'env'|\"env\")[ \t]*:[ \t]*(.*)$",
                          lines[index])
        if not header or not header.group(1).lstrip().startswith("{"):
            continue
        value, stop = inline_yaml_map_value(header.group(1).strip(), lines, index, end)
        if stop > index + 1 and inline_yaml_map_body(value) is not None:
            continuation_lines.update(range(index + 1, stop))
    return continuation_lines


def yaml_quoted_scalar_continuations(lines: list[str]) -> set[int]:
    continuation_lines: set[int] = set()
    quote: str | None = None
    escaped = False
    block_scalar_indent: int | None = None
    for line_index, line in enumerate(lines):
        line_indent = len(line) - len(line.lstrip(" \t"))
        if block_scalar_indent is not None:
            if not line.strip() or line_indent > block_scalar_indent:
                continuation_lines.add(line_index)
                continue
            block_scalar_indent = None
        if quote is None and not line.strip():
            continue
        if quote is None and line.lstrip().startswith("#"):
            continue
        scalar_header = strip_yaml_comments(line) if quote is None else line
        if quote is None and re.search(r":[ \t]*[|>](?:[1-9][+-]?|[+-][1-9]?)?[ \t]*$", scalar_header):
            block_scalar_indent = line_indent
            continue
        if quote is not None:
            continuation_lines.add(line_index)
        for index, char in enumerate(line):
            if quote == '"':
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
            elif quote == "'":
                if escaped:
                    escaped = False
                elif char == "'" and index + 1 < len(line) and line[index + 1] == "'":
                    escaped = True
                elif char == quote:
                    quote = None
            elif char == "#" and (index == 0 or line[index - 1].isspace()):
                break
            elif char in {"'", '"'} and inline_yaml_quote_starts(line[:index]):
                quote = char
    return continuation_lines


def workflow_command_authorized(source: str, command_offset: int) -> bool:
    """Check token and effective permissions inherited by one command's step."""
    lines = source.splitlines()
    command_line = source.count("\n", 0, command_offset)
    all_flow_map_continuations = yaml_env_flow_map_continuations(lines, 0, len(lines))
    quoted_scalar_continuations = yaml_quoted_scalar_continuations(lines)

    def indent(index: int) -> int:
        return len(lines[index]) - len(lines[index].lstrip(" \t"))

    def block(start: int, end: int, key: str, level: int) -> tuple[int, int] | None:
        for index in range(start, end):
            if indent(index) == level and yaml_key_header(lines[index], key):
                stop = index + 1
                while stop < end and (not lines[stop].strip() or lines[stop].lstrip().startswith("#")
                                      or stop in all_flow_map_continuations
                                      or indent(stop) > level
                                      or (key == "steps" and indent(stop) == level
                                          and lines[stop].lstrip(" \t").startswith("-"))):
                    stop += 1
                return index, stop
        return None

    def text(part: tuple[int, int] | None) -> str:
        return "\n".join(lines[part[0]:part[1]]) if part else ""

    jobs = block(0, len(lines), "jobs", 0)
    job = None
    job_indent = 0
    step = None
    step_indent = 0
    if jobs:
        jobs_start, jobs_end = jobs
        flow_map_continuations = yaml_env_flow_map_continuations(lines, jobs_start + 1, jobs_end)
        job_indents = [indent(i) for i in range(jobs_start + 1, jobs_end)
                       if lines[i].strip() and i not in flow_map_continuations
                       and indent(i) > 0 and yaml_mapping_key_header(lines[i])]
        if job_indents:
            job_indent = min(job_indents)
            for i in range(jobs_start + 1, jobs_end):
                if i in flow_map_continuations or indent(i) != job_indent or not yaml_mapping_key_header(lines[i]):
                    continue
                stop = i + 1
                while stop < jobs_end and (not lines[stop].strip() or lines[stop].lstrip().startswith("#")
                                           or indent(stop) > job_indent or stop in flow_map_continuations):
                    stop += 1
                if i <= command_line < stop:
                    job = (i, stop)
                    break
        if job:
            job_start, job_end = job
            job_fields_indent = mapping_child_indent(lines, job_start + 1, job_end, job_indent)
            step_indents = [indent(i) for i in range(job_start + 1, job_end)
                            if yaml_key_header(lines[i], "steps")
                            and indent(i) == job_fields_indent]
            if step_indents:
                steps_indent = min(step_indents)
                steps = block(job_start + 1, job_end, "steps", steps_indent)
                if steps:
                    steps_start, steps_end = steps
                    starts = [i for i in range(steps_start + 1, steps_end)
                              if i not in all_flow_map_continuations and i not in quoted_scalar_continuations
                              and indent(i) >= steps_indent
                              and lines[i].lstrip(" \t").startswith("-")]
                    if starts:
                        step_indent = min(indent(i) for i in starts)
                        starts = [i for i in starts if indent(i) == step_indent]
                        for position, i in enumerate(starts):
                            stop = starts[position + 1] if position + 1 < len(starts) else steps_end
                            if i <= command_line < stop:
                                step = (i, stop)
                                break

    workflow_env = block(0, len(lines), "env", 0)
    workflow_permissions = block(0, len(lines), "permissions", 0)
    job_fields_indent = mapping_child_indent(lines, job[0] + 1, job[1], job_indent) if job else job_indent + 2
    job_env = block(job[0] + 1, job[1], "env", job_fields_indent) if job else None
    job_permissions = block(job[0] + 1, job[1], "permissions", job_fields_indent) if job else None
    step_env, inline_step_env = workflow_step_env(lines, step, step_indent)
    workflow_env = include_flow_map_close(lines, workflow_env, len(lines))
    job_env = include_flow_map_close(lines, job_env, job[1]) if job else job_env
    step_env = include_flow_map_close(lines, step_env, step[1]) if step else step_env
    token = effective_workflow_token(lines, (workflow_env, job_env, step_env), (inline_step_env,))
    permissions = job_permissions or workflow_permissions
    actions_read = bool(re.search(r"(?m)^[ \t]+actions[ \t]*:[ \t]*read(?:[ \t]+#.*)?$", text(permissions)))
    return token and actions_read


def study_regex_hits(repo: Path, contents: dict[str, str]) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    js_exts = TYPESCRIPT_SUFFIXES | JAVASCRIPT_SUFFIXES

    for rel, source in contents.items():
        suffix = Path(rel).suffix.lower()
        if suffix == ".py":
            # Defect #12: raw identity-label membership accepts case, whitespace, and Unicode confusables.
            membership = re.compile(r"\b[A-Za-z_]\w*\s*\.\s*get\(\s*['\"](?:label|identity|email)['\"]\s*\)\s+in\s+[A-Za-z_]\w*")
            for match in membership.finditer(source):
                context = source[max(0, match.start() - 500):match.end()]
                if not re.search(r"normalize\s*\(|toNFKC\s*\(|normalize_label\s*\(", context):
                    hits.append({"rule_id": "pre_review.identity_label_normalization", "path": rel,
                                 "line": source.count("\n", 0, match.start()) + 1,
                                 "message": "identity label membership is compared literally without normalization"})
        if suffix in js_exts:
            # Defect #12: identity labels are compared literally without Unicode normalization.
            equality = re.compile(
                r"\b(?P<label>[A-Za-z_$]*(?:identity|label|email)[\w$]*)\s*(?:===|==)\s*"
                r"(?P<expected>(?:expected|known|allowed|trusted)[\w$]*)|"
                r"\b(?P<expected2>(?:expected|known|allowed|trusted)[\w$]*)\s*(?:===|==)\s*"
                r"(?P<label2>[A-Za-z_$]*(?:identity|label|email)[\w$]*)"
            )
            for match in equality.finditer(source):
                context = source[max(0, match.start() - 500):match.end()]
                if not re.search(r"\.\s*normalize\s*\(|toNFKC\s*\(", context):
                    hits.append({"rule_id": "pre_review.identity_label_normalization", "path": rel,
                                 "line": source.count("\n", 0, match.start()) + 1,
                                 "message": "identity label is compared literally without nearby Unicode normalization"})

            # Defect #31: a demo credential is written through a remote-capable DATABASE_URL without a target guard.
            direct_database_write = (
                re.search(r"\b(?:new\s+(?:Pool|Client)\s*\(|pg\.connect\s*\()", source)
                and re.search(r"\bDATABASE_URL\b", source)
                and re.search(r"password\s*[:=]\s*[\"'`][^\"'`]{4,}[\"'`]", source, re.I)
            )
            demo_credential_write = (
                re.search(r"\bdemoLoginPassword\b", source)
                and re.search(r"\b(?:prisma\.[\w.]+\.(?:create|update)|createAccount|updatePassword)\s*\(", source)
            )
            if (direct_database_write or demo_credential_write) and not re.search(r"target[-_]guard", source, re.I):
                match = re.search(r"\b(?:new\s+(?:Pool|Client)\s*\(|pg\.connect\s*\()", source)
                if not match:
                    match = re.search(r"\bdemoLoginPassword\b", source)
                hits.append({"rule_id": "pre_review.remote_database_seed_target_guard", "path": rel,
                             "line": source.count("\n", 0, match.start()) + 1,
                             "message": "demo password is seeded through DATABASE_URL without a target guard"})

            # Defect #33: hostname-plus-prefix validation remains instead of the shared database target guard.
            hostname = re.search(
                r"(?:const|let|var)\s+(\w+)\s*=\s*new\s+URL\s*\([^\n)]*(?:DATABASE_URL|databaseUrl)[^\n)]*\)",
                source,
            )
            direct_hostname = re.search(r"new\s+URL\s*\([^\n)]*\)\s*\.\s*hostname", source)
            legacy_host_check = bool(
                (hostname and re.search(rf"\b{re.escape(hostname.group(1))}\s*\.\s*hostname\s*\.\s*startsWith\s*\(", source))
                or (direct_hostname and re.search(r"\.\s*startsWith\s*\(", source))
            )
            if (legacy_host_check and not re.search(r"target[-_]guard", source, re.I)):
                hits.append({"rule_id": "pre_review.legacy_identity_hostname_guard", "path": rel,
                             "line": source.count("\n", 0, (hostname or direct_hostname).start()) + 1,
                             "message": "legacy hostname/startsWith validation does not use the shared target guard"})

            # Defect #30: WHATWG hostname vetting can disagree with the runtime PostgreSQL parser.
            mismatch = re.compile(
                r"(?:const|let|var)\s+(\w+)\s*=\s*new\s+URL\s*\(\s*(\w+)\s*\)"
                r"[\s\S]{0,1200}?\1\s*\.\s*hostname[\s\S]{0,1200}?"
                r"\b(?:Pool|Client)\s*\(\s*\{[\s\S]{0,500}?connectionString\s*:\s*\2\b"
            )
            for match in mismatch.finditer(source):
                hits.append({"rule_id": "pre_review.url_parser_mismatch", "path": rel,
                             "line": source.count("\n", 0, match.start()) + 1,
                             "message": "WHATWG URL hostname vetting precedes use of the same value by a database client"})
            # Defect #30: database-host authorization based on WHATWG URL.hostname can miss pg query overrides.
            host_check = re.compile(
                r"(?:new\s+URL\s*\(|parseUrl\s*=)[\s\S]{0,1800}?(?:DATABASE_URL|databaseUrl|connectionString)[\s\S]{0,1800}?\.hostname"
            )
            parser_import = re.search(r"pg-connection-string", source) and re.search(r"\bparse\s*\([^\n)]*(?:DATABASE_URL|databaseUrl|connectionString)", source)
            for match in host_check.finditer(source):
                if not parser_import:
                    hits.append({"rule_id": "pre_review.url_parser_mismatch", "path": rel,
                                 "line": source.count("\n", 0, match.start()) + 1,
                                 "message": "database host is authorized with WHATWG URL.hostname instead of pg-connection-string"})

            # Defect #51: `void` suppresses lint while an async function's rejection is unhandled.
            async_names = set(re.findall(r"(?m)\b(?:const|let|var)\s+(\w+)\s*=\s*async\b|\basync\s+function\s+(\w+)", source))
            async_names = {name for pair in async_names for name in pair if name}
            call_names = "|".join(map(re.escape, sorted(async_names | {"continueHop", "readToken"})))
            floating = re.compile(rf"(?m)^\s*void\s+(?:{call_names})\s*\([^;\n]*\)\s*;") if call_names else re.compile(r"(?!)")
            for match in floating.finditer(source):
                hits.append({"rule_id": "pre_review.no_floating_promises", "path": rel,
                             "line": source.count("\n", 0, match.start()) + 1,
                             "message": "Promise expression is neither awaited nor returned"})

        if suffix in {".md", ".markdown"}:
            # Defect #52: markdown emphasis swallows a glob-like token outside code spans.
            hits.extend(markdown_glob_hits(rel, source))

    # Defect #48: gh run lookups need both a token in the job and actions:read permission.
    for rel, source in contents.items():
        if not rel.startswith(".github/workflows/") or Path(rel).suffix.lower() not in {".yml", ".yaml"}:
            continue
        command_pattern = r"\bgh\s+run\s+(?:view|list)\b|ship-gate(?:\.py)?\s+check"
        command = re.search(
            rf"(?m)^[ \t]*(?:-[ \t]*)?(?:run|script)[ \t]*:[ \t]*[^\n]*{command_pattern}", source)
        command_offset = command.start() if command else None
        if command_offset is None:
            # Defect #48: shell commands also appear inside YAML literal/folded run blocks.
            block = re.compile(
                r"(?m)^[ \t]*(?:-[ \t]*)?(?:run|script)[ \t]*:[ \t]*[|>]"
                r"(?:[1-9][+-]?|[+-][1-9]?)?[ \t]*(?:#.*)?\n"
                r"(?P<body>(?:[ \t]{2,}[^\n]*(?:\n|$))+)"
            )
            for block_match in block.finditer(source):
                embedded_command = re.search(command_pattern, block_match.group("body"))
                if embedded_command:
                    command_offset = block_match.start("body") + embedded_command.start()
                    break
        token = actions_read = False
        if command_offset is not None:
            lines = source.splitlines()
            command_line = source.count("\n", 0, command_offset)

            def line_indent(index: int) -> int:
                return len(lines[index]) - len(lines[index].lstrip(" \t"))

            all_flow_map_continuations = yaml_env_flow_map_continuations(lines, 0, len(lines))
            quoted_scalar_continuations = yaml_quoted_scalar_continuations(lines)

            def find_block(start: int, end: int, key: str, indent: int) -> tuple[int, int] | None:
                for index in range(start, end):
                    if line_indent(index) == indent and yaml_key_header(lines[index], key):
                        stop = index + 1
                        while stop < end and (not lines[stop].strip()
                                              or lines[stop].lstrip().startswith("#")
                                              or stop in all_flow_map_continuations
                                              or line_indent(stop) > indent
                                              or (key == "steps" and line_indent(stop) == indent
                                                  and lines[stop].lstrip(" \t").startswith("-"))):
                            stop += 1
                        return index, stop
                return None

            def block_text(block: tuple[int, int] | None) -> str:
                return "\n".join(lines[block[0]:block[1]]) if block else ""

            jobs_block = find_block(0, len(lines), "jobs", 0)
            job_block = None
            job_indent = 0
            steps_block = None
            step_block = None
            step_indent = 0
            if jobs_block:
                jobs_start, jobs_end = jobs_block
                flow_map_continuations = yaml_env_flow_map_continuations(lines, jobs_start + 1, jobs_end)
                job_indents = [line_indent(i) for i in range(jobs_start + 1, jobs_end)
                               if lines[i].strip() and i not in flow_map_continuations and line_indent(i) > 0
                               and yaml_mapping_key_header(lines[i])]
                if job_indents:
                    job_indent = min(job_indents)
                    for i in range(jobs_start + 1, jobs_end):
                        if i in flow_map_continuations or line_indent(i) != job_indent or not yaml_mapping_key_header(lines[i]):
                            continue
                        stop = i + 1
                        while stop < jobs_end and (not lines[stop].strip()
                                                   or lines[stop].lstrip().startswith("#")
                                                   or line_indent(stop) > job_indent
                                                   or stop in flow_map_continuations):
                            stop += 1
                        if i <= command_line < stop:
                            job_block = (i, stop)
                            break
                if job_block:
                    job_start, job_end = job_block
                    job_fields_indent = mapping_child_indent(lines, job_start + 1, job_end, job_indent)
                    step_indents = [line_indent(i) for i in range(job_start + 1, job_end)
                                    if yaml_key_header(lines[i], "steps")
                                    and line_indent(i) == job_fields_indent]
                    if step_indents:
                        steps_indent = min(step_indents)
                        steps_block = find_block(job_start + 1, job_end, "steps", steps_indent)
                        if steps_block:
                            steps_start, steps_end = steps_block
                            step_starts = [i for i in range(steps_start + 1, steps_end)
                                           if i not in all_flow_map_continuations
                                           and i not in quoted_scalar_continuations
                                           and line_indent(i) >= steps_indent
                                           and lines[i].lstrip(" \t").startswith("-")]
                            if step_starts:
                                step_indent = min(line_indent(i) for i in step_starts)
                                scoped_steps = [i for i in step_starts if line_indent(i) == step_indent]
                                for position, i in enumerate(scoped_steps):
                                    stop = scoped_steps[position + 1] if position + 1 < len(scoped_steps) else steps_end
                                    if i <= command_line < stop:
                                        step_block = (i, stop)
                                        break

            workflow_env = find_block(0, len(lines), "env", 0)
            workflow_permissions = find_block(0, len(lines), "permissions", 0)
            job_fields_indent = (mapping_child_indent(lines, job_block[0] + 1, job_block[1], job_indent)
                                 if job_block else job_indent + 2)
            job_env = find_block(job_block[0] + 1, job_block[1], "env", job_fields_indent) if job_block else None
            job_permissions = find_block(job_block[0] + 1, job_block[1], "permissions", job_fields_indent) if job_block else None
            step_env, inline_step_env = workflow_step_env(lines, step_block, step_indent)
            workflow_env = include_flow_map_close(lines, workflow_env, len(lines))
            job_env = include_flow_map_close(lines, job_env, job_block[1]) if job_block else job_env
            step_env = include_flow_map_close(lines, step_env, step_block[1]) if step_block else step_env
            token = effective_workflow_token(lines, (workflow_env, job_env, step_env), (inline_step_env,))
            effective_permissions = job_permissions or workflow_permissions
            actions_read = bool(re.search(r"(?m)^[ \t]+actions[ \t]*:[ \t]*read(?:[ \t]+#.*)?$",
                                         block_text(effective_permissions)))

        if command_offset is not None and (not token or not actions_read):
            hits.append({"rule_id": "pre_review.workflow_gh_run_permissions", "path": rel,
                         "line": source.count("\n", 0, command_offset) + 1,
                         "message": "workflow gh run lookup is missing explicit GH_TOKEN or actions:read permission"})

        # Defect #48: validate every other command independently, not just the first match.
        command_offsets: list[int] = []
        run_line = re.compile(r"(?m)^[ \t]*(?:-[ \t]*)?(?:run|script)[ \t]*:[ \t]*(?P<value>[^\n]*)")
        for run_match in run_line.finditer(source):
            command_offsets.extend(run_match.start("value") + match.start()
                                   for match in re.finditer(command_pattern, run_match.group("value")))
        block = re.compile(
            r"(?m)^[ \t]*(?:-[ \t]*)?(?:run|script)[ \t]*:[ \t]*[|>]"
            r"(?:[1-9][+-]?|[+-][1-9]?)?[ \t]*(?:#.*)?\n"
            r"(?P<body>(?:[ \t]{2,}[^\n]*(?:\n|$)|[ \t]*\n)+)"
        )
        for block_match in block.finditer(source):
            command_offsets.extend(block_match.start("body") + match.start()
                                   for match in re.finditer(command_pattern, block_match.group("body")))
        first_line = source.count("\n", 0, command_offset) if command_offset is not None else None
        for offset in sorted(set(command_offsets)):
            if source.count("\n", 0, offset) == first_line:
                continue  # The existing first-command check already handles this line.
            if not workflow_command_authorized(source, offset):
                hits.append({"rule_id": "pre_review.workflow_gh_run_permissions", "path": rel,
                             "line": source.count("\n", 0, offset) + 1,
                             "message": "workflow gh run lookup is missing explicit GH_TOKEN or actions:read permission"})

    # Defect #49: an explicitly cited uppercase constant must exist in tracked code, not only review prose.
    cited = re.compile(r"(?i)\b(?:cited|citation(?:\s+of)?|reference\s+to)\b[^\n]{0,100}\b([A-Z][A-Z0-9]*_[A-Z0-9_]{2,})\b")
    for rel, source in contents.items():
        if Path(rel).suffix.lower() not in {".md", ".markdown"}:
            continue
        for match in cited.finditer(source):
            symbol = match.group(1)
            declaration = re.compile(
                rf"(?m)^\s*(?:(?:export|const|let|var)\s+)?{re.escape(symbol)}\s*(?:=|:)"
            )
            grep_declaration = (
                rf"^[[:space:]]*(export[[:space:]]+)?(const[[:space:]]+|let[[:space:]]+|var[[:space:]]+)?"
                rf"{re.escape(symbol)}[[:space:]]*(=|:)"
            )
            present_in_changed_code = any(declaration.search(code) for other, code in contents.items()
                                          if Path(other).suffix.lower() in js_exts | {".py", ".go", ".java", ".c", ".h", ".sh"})
            if not present_in_changed_code:
                # Search declarations only; comments and incidental references are not definitions.
                result = run_capture(["git", "grep", "-n", "-E", "-e", grep_declaration, "--",
                                     "*.py", "*.ts", "*.tsx", "*.js", "*.mjs", "*.go", "*.java", "*.c", "*.h", "*.sh"], repo)
                if result.returncode:
                    hits.append({"rule_id": "pre_review.cited_symbol_exists", "path": rel,
                                 "line": source.count("\n", 0, match.start()) + 1,
                                 "message": f"review prose cites {symbol}, but no tracked source definition/reference exists"})

    # Defect #55: unresolved plan items cannot be reported as passing in the rewalk JSON.
    plan_path = next((path for path in contents if path.endswith(".qa/plan.md")), None)
    rewalk_path = next((path for path in contents if path.endswith(".qa/rewalk.json")), None)
    if plan_path or rewalk_path:
        plan_path = plan_path or ".qa/plan.md"
        rewalk_path = rewalk_path or ".qa/rewalk.json"
        for companion in (plan_path, rewalk_path):
            if companion not in contents:
                try:
                    contents[companion] = (repo / companion).read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    pass
        plan_path = plan_path if plan_path in contents else None
        rewalk_path = rewalk_path if rewalk_path in contents else None
    if plan_path and rewalk_path:
        plan = contents[plan_path]
        rewalk = contents[rewalk_path]
        # Defect #55: an escalated or unfixed plan item conflicts with an all-green rewalk.
        open_item = re.compile(r"(?is)(?:\bR\d+/CL-\d+\b|\bCL-\d+\s*\(R\d+\))[\s\S]{0,500}?(?:unresolved|not resolved|still open|escalated|not fixed|remains open)")
        all_pass = re.search(r"(?is)\"verdict\"\s*:\s*\"PASS\"", rewalk) and not re.search(
            r"(?is)\"verdict\"\s*:\s*\"(?:FAIL|BLOCKED|ERROR)\"", rewalk
        )
        if open_item.search(plan) and all_pass:
            passing = re.search(r"(?is)\"verdict\"\s*:\s*\"PASS\"", rewalk)
            hits.append({"rule_id": "pre_review.plan_rewalk_unresolved_conflict", "path": rewalk_path,
                         "line": rewalk.count("\n", 0, passing.start()) + 1,
                         "message": "plan retains an unresolved/escalated item while the rewalk reports only PASS"})
        unresolved = re.compile(r"(?im)^.*\b(R\d+/[A-Z][A-Z0-9_-]*-\d+)\b.*\b(?:unresolved|not resolved|still open)\b.*$")
        for match in unresolved.finditer(plan):
            item_id = match.group(1)
            escaped_id = re.escape(item_id)
            passing = re.compile(rf"(?is)[\"'](?:id|key)[\"']\s*:\s*[\"']{escaped_id}[\"'][^{{}}]{{0,400}}[\"'](?:status|verdict|result)[\"']\s*:\s*[\"']PASS[\"']")
            if passing.search(rewalk):
                hits.append({"rule_id": "pre_review.plan_rewalk_unresolved_conflict", "path": rewalk_path,
                             "line": rewalk.count("\n", 0, passing.search(rewalk).start()) + 1,
                             "message": f"rewalk reports {item_id} as PASS while the plan still marks it unresolved"})

    return hits


def builtin_rule_scan(repo: Path, paths: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    contents: dict[str, str] = {}
    scanned = 0
    for rel in paths:
        if is_pre_review_fixture(rel):
            continue
        path = Path(rel)
        if path.suffix.lower() not in ({".py", ".yml", ".yaml", ".md", ".markdown", ".json"} | TYPESCRIPT_SUFFIXES | JAVASCRIPT_SUFFIXES):
            continue
        target = (repo / path).resolve()
        try:
            target.relative_to(repo)
            source = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            continue
        scanned += 1
        contents[rel] = source
        if path.suffix.lower() == ".py":
            # Defect #45: Python's Unicode-aware digit class disagrees with the downstream ASCII parser.
            hits.extend(python_digit_rule(rel, source))
            hits.extend(external_response_shape_hits(rel, source))
        if path.suffix.lower() in {".yml", ".yaml"} and rel.startswith(".github/workflows/"):
            # Port of pre_review.github_token_permissions: token use requires an explicit permissions block.
            token_use = bool(re.search(r"(?:secrets\.GITHUB_TOKEN|\bGH_TOKEN\b)", source))
            permission_declared = bool(re.search(r"(?m)^\s*permissions\s*:", source))
            if token_use and not permission_declared:
                match = re.search(r"(?:secrets\.GITHUB_TOKEN|\bGH_TOKEN\b)", source)
                hits.append({"rule_id": "pre_review.github_token_permissions", "path": rel,
                             "line": source.count("\n", 0, match.start()) + 1,
                             "message": "workflow uses the GitHub token without declaring permissions"})
    hits.extend(study_regex_hits(repo, contents))
    check = {"name": "built-in-rule-scan", "command": ["pre-review built-in rules", *paths],
             "status": "fail" if hits else "pass", "exit_code": 1 if hits else 0,
             "output_tail": f"scanned {scanned} changed source/config file(s); {len(BUILTIN_RULE_IDS)} built-in rule(s) active; {len(hits)} hit(s)",
             "duration_ms": 0}
    return hits, check


def project_rule_files(repo: Path) -> list[Path]:
    root = repo / ".review-rules"
    if not root.is_dir():
        return []
    files = []
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in {".yaml", ".yml"} or not path.is_file():
            continue
        resolved = path.resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        files.append(path)
    return files


def semgrep_result(raw: bytes, repo: Path) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    hits = []
    for item in decoded.get("results", []):
        hits.append({"rule_id": item.get("check_id", "unknown"),
                     "path": os.path.relpath(item.get("path", ""), repo),
                     "line": item.get("start", {}).get("line"),
                     "message": item.get("extra", {}).get("message", "Semgrep finding")})
    return hits


def markdown_summary(packet: dict[str, Any]) -> bytes:
    lines = ["# Pre-review summary", "", f"- Repository: `{packet['repo']}`",
             f"- Head: `{packet['head_sha']}`", f"- Base: `{packet['base']['ref']}` ({packet['base']['sha']})",
             f"- Review scope: `{packet.get('review_scope', 'working-tree')}`",
             f"- Execution mode: `{packet.get('execution', {}).get('mode', 'unknown')}`",
             f"- Source porcelain unchanged: `{str(packet.get('source_porcelain_unchanged', False)).lower()}`",
             f"- Dirty: `{str(packet['dirty']).lower()}`", f"- Changed paths: {packet['changed_path_count']}",
             f"- Raw diff bytes: {packet['raw_diff_bytes']}", f"- Packet bytes: {packet['packet_bytes']} / {packet['packet_budget_bytes']}",
             f"- Worktree-only paths excluded from range: {len(packet.get('excluded_worktree_paths', []))}",
             "", "## Excluded worktree paths", ""]
    lines.extend(f"- `{path}`" for path in packet.get("excluded_worktree_paths", []))
    lines.extend(["", "## Checks", ""])
    for command in packet["commands"]:
        verification = f"; verification {command['verification']}" if command.get("verification") else ""
        duration = f"; {command['duration_ms']} ms" if command.get("duration_ms") is not None else ""
        lines.append(f"- `{command['name']}`: **{command['status']}** (exit {command['exit_code']}){verification}{duration}; {command['output_tail'][:240]}")
    lines.extend(["", "## Rule hits", ""])
    if packet["rule_hits"]:
        for hit in packet["rule_hits"]:
            lines.append(f"- `{hit['rule_id']}` — `{hit['path']}:{hit.get('line')}`: {hit['message']}")
    else:
        lines.append("- None")
    lines.extend(["", "## Built-in rule coverage", "",
                  f"- Dependency-free rules active: {len(packet.get('active_builtin_rules', []))}",
                  f"- Study R/S defect classes covered: {packet.get('study_static_covered', 0)}/{packet.get('study_static_total', 0)}"])
    lines.extend(["", "## Active rule files", ""])
    lines.extend(f"- `{path}`" for path in packet["active_rule_files"])
    if not packet["active_rule_files"]:
        lines.append("- None")
    if packet["budget_excess_bytes"]:
        lines.extend(["", f"Packet source exceeded budget by {packet['budget_excess_bytes']} bytes before bounded truncation."])
    if packet.get("changed_paths_omitted"):
        lines.extend(["", f"Changed paths omitted from this packet: {packet['changed_paths_omitted']}; see the repository diff for the complete list."])
    if packet.get("rule_hits_omitted"):
        lines.extend(["", f"Rule hits omitted from this packet: {packet['rule_hits_omitted']}; packet status is failed."])
    return ("\n".join(lines) + "\n").encode("utf-8")


def finalize_packet(packet: dict[str, Any]) -> tuple[bytes, bytes]:
    packet["packet_bytes"] = 0
    packet["budget_excess_bytes"] = 0
    packet["changed_path_count"] = len(packet["changed_paths"])
    packet["changed_paths_omitted"] = 0
    packet["rule_hit_count"] = len(packet["rule_hits"])
    packet["rule_hits_omitted"] = 0
    packet["packet_overflow"] = False
    def encoded() -> tuple[bytes, bytes]:
        json_bytes = (json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        markdown_bytes = markdown_summary(packet)
        return json_bytes, markdown_bytes
    def settle() -> tuple[bytes, bytes]:
        for _ in range(8):
            json_bytes, markdown_bytes = encoded()
            total = len(json_bytes) + len(markdown_bytes)
            if packet["packet_bytes"] == total:
                return json_bytes, markdown_bytes
            packet["packet_bytes"] = total
        return encoded()
    json_bytes, markdown_bytes = settle()
    if len(json_bytes) + len(markdown_bytes) > PACKET_BUDGET:
        packet["packet_overflow"] = True
        packet["commands"].append({"name": "packet-budget", "command": ["pre-review packet-size limit"],
                                   "status": "fail", "exit_code": 1,
                                   "duration_ms": 0,
                                   "output_tail": "evidence was compacted to keep JSON plus Markdown within 64 KiB"})
        packet["budget_excess_bytes"] = len(json_bytes) + len(markdown_bytes) - PACKET_BUDGET
        for command in packet["commands"]:
            tail = command.get("output_tail", "")
            if len(tail.encode("utf-8")) > 256:
                raw = tail.encode("utf-8")
                command["output_tail"] = raw[-256:].decode("utf-8", errors="replace")
                command["output_tail_omitted_bytes"] = len(raw) - 256
        json_bytes, markdown_bytes = settle()

        original_paths = packet["changed_paths"]
        packet["changed_paths_sha256"] = hashlib.sha256(
            json.dumps(original_paths, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        original_hits = packet["rule_hits"]
        packet["rule_hits_sha256"] = hashlib.sha256(
            json.dumps(original_hits, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        while len(json_bytes) + len(markdown_bytes) > PACKET_BUDGET:
            if packet["changed_paths"]:
                keep = len(packet["changed_paths"]) // 2
                packet["changed_paths"] = packet["changed_paths"][:keep]
                packet["changed_paths_omitted"] = packet["changed_path_count"] - keep
            elif packet["rule_hits"]:
                keep = len(packet["rule_hits"]) // 2
                packet["rule_hits"] = packet["rule_hits"][:keep]
                packet["rule_hits_omitted"] = packet["rule_hit_count"] - keep
            else:
                oversized = next((item for item in packet["commands"] if item.get("command")), None)
                if oversized and len(oversized["command"]) > 1:
                    omitted = len(oversized["command"]) - 1
                    oversized["command"] = oversized["command"][:1]
                    oversized["command_args_omitted"] = omitted
                elif oversized and oversized.get("output_tail"):
                    oversized["output_tail"] = ""
                else:
                    break
            json_bytes, markdown_bytes = settle()
    total = len(json_bytes) + len(markdown_bytes)
    if total > PACKET_BUDGET:
        raise PreReviewError(f"minimal packet still exceeds 64 KiB by {total - PACKET_BUDGET} bytes")
    return json_bytes, markdown_bytes


def write_packet(output_dir: Path, packet: dict[str, Any]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_bytes, markdown_bytes = finalize_packet(packet)
    json_path, markdown_path = output_dir / "pre-review.json", output_dir / "pre-review.md"
    json_path.write_bytes(json_bytes)
    markdown_path.write_bytes(markdown_bytes)
    return json_path, markdown_path


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help=f"base ref to compare (default: {DEFAULT_BASE})")
    parser.add_argument("--base-sha", help="resolved base commit SHA from the source repository")
    parser.add_argument("--merge-base-sha", help="resolved source-repository merge-base commit SHA")
    parser.add_argument("--head-sha", help="reviewed head SHA; defaults to the source repository HEAD")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository directory (default: current directory)")
    parser.add_argument("--output-dir", type=Path, help="packet directory (default: a temp directory outside the repo)")
    parser.add_argument("--skip-tests", action="store_true",
                        help="record focused tests as skipped without running them (default: focused tests enabled)")
    parser.add_argument("--skip-repo-lint", action="store_true",
                        help="record the repository lint script as skipped without running it")
    parser.add_argument("--timeout-scale", type=float, default=1.0,
                        help="multiply each check timeout by this positive value (default: 1.0)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    if args.timeout_scale <= 0:
        make_parser().error("--timeout-scale must be greater than zero")
    worktree: Path | None = None
    cleanup_worktree: Any | None = None
    source_status_before = b""
    source_repo = Path.cwd()
    execution_mode = "in-place"
    setup_error: str | None = None
    tracked_clean = False
    try:
        source_repo = resolve_repo(args.repo.resolve())
        source_status_before = git_output(source_repo, "status", "--porcelain")
        source_head_sha = os.fsdecode(git_output(source_repo, "rev-parse", "HEAD").strip())
        reviewed_head_sha = args.head_sha or source_head_sha
        resolved_head = run_capture(["git", "rev-parse", "--verify", f"{reviewed_head_sha}^{{commit}}"], source_repo)
        if resolved_head.returncode:
            raise PreReviewError("reviewed head SHA is not available in the source repository")
        reviewed_head_sha = os.fsdecode(resolved_head.stdout.strip())
        base_ref, base_sha, merge_sha = resolve_base(source_repo, args.base, args.base_sha, args.merge_base_sha)
        free_bytes = shutil.disk_usage(source_repo).free
        tracked_clean = tracked_tree_clean(source_repo)
        execution_mode, setup_error = execution_plan(
            tracked_clean, source_head_sha == reviewed_head_sha, free_bytes)
        repo = source_repo
        if execution_mode == "detached-worktree":
            worktree, setup_error, cleanup_worktree = add_detached_worktree(source_repo, reviewed_head_sha)
            if worktree:
                repo = worktree.resolve()
                if shutil.disk_usage(source_repo).free < MIN_FREE_BYTES:
                    free_bytes = shutil.disk_usage(source_repo).free
                    setup_error = f"environment: disk {free_bytes / (1024**3):.1f} GiB free is below 20 GiB; dependency hydration skipped"
                else:
                    setup_error = hydrate_checkout(repo, Path(tempfile.gettempdir()))

        repo_key = hashlib.sha256(str(source_repo).encode("utf-8")).hexdigest()[:16]
        output_dir = args.output_dir if args.output_dir and args.output_dir.is_absolute() else (
            source_repo / args.output_dir if args.output_dir else Path(tempfile.gettempdir()) / "agent-config-kit-pre-review" / repo_key / str(os.getpid())
        )
        output_dir = output_dir.resolve()
        if output_dir.is_relative_to(source_repo) or (repo != source_repo and output_dir.is_relative_to(repo)):
            raise PreReviewError("output directory must be outside the reviewed repository")
        pr_mode = args.base is not None or args.base_sha is not None or args.merge_base_sha is not None
        if args.head_sha is not None:
            pr_mode = True
        paths, dirty, raw_diff_bytes, excluded_worktree_paths = changed_paths(
            repo, merge_sha, output_dir, include_worktree=not pr_mode)
        output_dir.mkdir(parents=True, exist_ok=True)
    except PreReviewError as error:
        if cleanup_worktree:
            cleanup_worktree()
        print(f"pre-review: {error}", file=sys.stderr)
        return 2

    head_sha = reviewed_head_sha
    commands: list[dict[str, Any]] = []
    target_error = setup_error if execution_mode == "unverified" or (execution_mode == "detached-worktree" and not worktree) else None
    dependency_error = setup_error if worktree else None

    def run_check(name: str, argv: list[str], *, timeout: float = DEFAULT_CHECK_TIMEOUT_SECONDS,
                  skip_reason: str | None = None, requires_hydration: bool = False) -> dict[str, Any]:
        return record_command(name, argv, repo, timeout=timeout, timeout_scale=args.timeout_scale,
                              skip_reason=skip_reason, output_dir=output_dir,
                              unavailable_reason=target_error or (dependency_error if requires_hydration else None))

    builtin_started = time.monotonic()
    hits, built_in = builtin_rule_scan(repo, paths)
    built_in["duration_ms"] = round((time.monotonic() - builtin_started) * 1000)
    commands.append(built_in)

    package, manager = package_metadata(repo)
    has_ts = any(Path(path).suffix.lower() in TYPESCRIPT_SUFFIXES for path in paths)
    has_py = any(Path(path).suffix.lower() == ".py" for path in paths)
    has_md = any(Path(path).suffix.lower() in {".md", ".markdown"} for path in paths)
    workflows = [path for path in paths if path.startswith(".github/workflows/") and Path(path).suffix.lower() in {".yml", ".yaml"}]

    typecheck = readonly_typecheck_command(repo, package, manager)
    if typecheck:
        commands.append(run_check("repo-typecheck", typecheck, requires_hydration=True))
    elif (repo / "tsconfig.json").is_file():
        tsc = binary_path(repo, "tsc")
        commands.append(run_check("typescript-typecheck", [tsc, "--noEmit", "--incremental", "false"] if tsc else [],
                                  skip_reason=None if tsc else "tsc not installed", requires_hydration=True))
    elif has_ts:
        commands.append(run_check("typescript-typecheck", [], skip_reason="no configured TypeScript project",
                                  requires_hydration=True))

    if has_py and has_mypy_config(repo):
        mypy = binary_path(repo, "mypy")
        python_files = [path for path in paths if path.endswith(".py")]
        commands.append(run_check("python-mypy", [mypy, *command_paths(repo, python_files)] if mypy else [],
                                  skip_reason=None if mypy else "mypy not installed"))

    lint = package_script(package, manager, ("lint", "lint:check", "check:lint"))
    if lint:
        lint_check = run_check("repo-lint", lint, requires_hydration=True,
                               skip_reason="skipped by --skip-repo-lint" if args.skip_repo_lint else None)
        if pr_mode:
            lint_check = classify_outside_diff_lint(lint_check, paths)
        else:
            lint_check.pop("_raw_output", None)
        commands.append(lint_check)

    if has_ts:
        eslint = binary_path(repo, "eslint")
        config_present = any((repo / name).exists() for name in ("eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml"))
        ts_files = [path for path in paths if Path(path).suffix.lower() in TYPESCRIPT_SUFFIXES]
        if eslint and config_present:
            commands.append(run_check("eslint-no-floating-promises", [eslint, "--rule", "@typescript-eslint/no-floating-promises:error", *command_paths(repo, ts_files)], requires_hydration=True))
        else:
            reason = "eslint not installed" if not eslint else "no configured eslint project"
            commands.append(run_check("eslint-no-floating-promises", [], skip_reason=reason, requires_hydration=True))

    if workflows:
        actionlint = binary_path(repo, "actionlint")
        commands.append(run_check("actionlint", [actionlint, *command_paths(repo, workflows)] if actionlint else [],
                                  skip_reason=None if actionlint else "actionlint not installed"))

    if has_md:
        markdownlint = binary_path(repo, "markdownlint-cli2") or binary_path(repo, "markdownlint")
        markdown_files = [path for path in paths if Path(path).suffix.lower() in {".md", ".markdown"}]
        commands.append(run_check("markdownlint", [markdownlint, *command_paths(repo, markdown_files)] if markdownlint else [],
                                  skip_reason=None if markdownlint else "markdownlint not installed"))

    semgrep = binary_path(repo, "semgrep")
    active_rule_files: list[Path] = [starter_rules_path()] if paths else []
    project_rules = project_rule_files(repo)
    source_paths = [path for path in paths
                    if not is_pre_review_fixture(path)
                    and Path(path).suffix.lower() in ({".py", ".c", ".h", ".go", ".java", ".yaml", ".yml"} | TYPESCRIPT_SUFFIXES | JAVASCRIPT_SUFFIXES)]
    if source_paths:
        if semgrep:
            active_rule_files = list(dict.fromkeys([starter_rules_path(), *project_rules]))
            semgrep_args = [semgrep, "scan", "--json", "--error"]
            for rule_file in active_rule_files:
                semgrep_args.extend(["--config", str(rule_file)])
            semgrep_args.extend(command_paths(repo, source_paths))
            if target_error:
                commands.append(workspace_error("semgrep", target_error))
            else:
                try:
                    semgrep_started = time.monotonic()
                    semgrep_run = run_capture(semgrep_args, repo, timeout=180 * args.timeout_scale,
                                              env=repo_command_environment(repo, output_dir))
                    semgrep_tail = output_tail(semgrep_run.stdout).replace(str(repo), "<repo>")
                    is_environment_error = semgrep_run.returncode != 0 and environment_error(semgrep_tail)
                    if not is_environment_error:
                        hits.extend(semgrep_result(semgrep_run.stdout, repo))
                    commands.append({"name": "semgrep", "command": semgrep_args,
                                     "status": "error" if is_environment_error else ("fail" if semgrep_run.returncode else "pass"),
                                     "exit_code": semgrep_run.returncode,
                                     "duration_ms": round((time.monotonic() - semgrep_started) * 1000),
                                     "output_tail": semgrep_tail})
                    if is_environment_error:
                        commands[-1].update(verification="unverified", error_kind="environment",
                                            output_tail=(semgrep_tail + "\nenvironment error; result is unverified").strip())
                except subprocess.TimeoutExpired as error:
                    raw = error.stdout or b""
                    if isinstance(raw, str):
                        raw = raw.encode("utf-8", errors="replace")
                    commands.append({"name": "semgrep", "command": semgrep_args, "status": "timeout",
                                     "exit_code": None, "verification": "unverified",
                                     "duration_ms": round((time.monotonic() - semgrep_started) * 1000),
                                     "output_tail": (output_tail(raw) + "\ncommand timed out; result is unverified").strip()})
        else:
            commands.append(run_check("semgrep", [], skip_reason="semgrep not installed"))

    tests = related_test_paths(repo, paths)
    python_tests = [path for path in tests if path.endswith(".py")]
    for name, argv, reason in focused_test_commands(repo, tests, output_dir, args.skip_tests,
                                                     timeout_scale=args.timeout_scale):
        timeout = (focused_python_test_timeout(repo, python_tests)
                   if name == "focused-python-tests" else DEFAULT_CHECK_TIMEOUT_SECONDS)
        commands.append(run_check(name, argv, timeout=timeout, skip_reason=reason,
                                  requires_hydration=name in {"focused-playwright-tests",
                                                              "focused-typescript-tests",
                                                              "focused-node-tests"}))

    # Keep rule IDs stable and avoid reporting the same finding from both the
    # built-in safety net and Semgrep.
    unique_hits: dict[tuple[Any, ...], dict[str, Any]] = {}
    for hit in hits:
        key = (hit.get("rule_id"), hit.get("path"), hit.get("line"))
        unique_hits.setdefault(key, hit)
    cleanup_failed = False
    if cleanup_worktree:
        cleanup_result = cleanup_worktree()
        if cleanup_result.returncode:
            cleanup_failed = True
            commands.append(workspace_error(
                "temporary-worktree-cleanup",
                "environment: git worktree remove failed: " + output_tail(cleanup_result.stdout).strip()))
    try:
        source_status_after = git_output(source_repo, "status", "--porcelain")
        source_head_after = os.fsdecode(git_output(source_repo, "rev-parse", "HEAD").strip())
        status_check = porcelain_result(source_status_before, source_status_after)
        commands.append(status_check)
        if source_head_after != source_head_sha:
            commands.append({"name": "source-head-unchanged", "command": ["git", "rev-parse", "HEAD"],
                             "status": "fail", "exit_code": 1,
                             "output_tail": "source HEAD changed during pre-review",
                             "duration_ms": 0})
    except PreReviewError as error:
        source_status_after = b""
        commands.append(workspace_error("source-porcelain-unchanged", f"environment: {error}"))
    packet = {
        "schema_version": 1,
        "repo": str(repo),
        "source_repo": str(source_repo),
        "head_sha": head_sha,
        "execution": {"mode": execution_mode, "reviewed_head_sha": reviewed_head_sha,
                      "source_head_sha": source_head_sha, "tracked_tree_clean": tracked_clean,
                      "preparation_error": setup_error},
        "source_porcelain_unchanged": source_status_before == source_status_after,
        "temporary_worktree_cleanup_failed": cleanup_failed,
        "base": {"ref": base_ref, "sha": base_sha, "merge_base_sha": merge_sha},
        "review_scope": "committed-range" if pr_mode else "working-tree",
        "dirty": dirty,
        "changed_paths": paths,
        "excluded_worktree_paths": excluded_worktree_paths,
        "commands": commands,
        "rule_hits": list(unique_hits.values()),
        "active_builtin_rules": BUILTIN_RULE_IDS,
        "study_static_covered": len(STUDY_STATIC_DEFECT_RULES),
        "study_static_total": 11,
        "study_static_defect_rules": STUDY_STATIC_DEFECT_RULES,
        "active_rule_files": [str(path.resolve()) for path in active_rule_files],
        "available_project_rule_files": [path.relative_to(repo).as_posix() for path in project_rules],
        "raw_diff_bytes": raw_diff_bytes,
        "packet_bytes": 0,
        "packet_budget_bytes": PACKET_BUDGET,
        "budget_excess_bytes": 0,
    }
    try:
        json_path, markdown_path = write_packet(output_dir, packet)
    except OSError as error:
        print(f"pre-review: cannot write packet: {error}", file=sys.stderr)
        return 2
    print(f"JSON packet: {json_path}")
    print(f"Markdown summary: {markdown_path}")
    print(f"Packet bytes: {packet['packet_bytes']} / {PACKET_BUDGET}")
    if packet["budget_excess_bytes"]:
        print(f"Packet budget excess: {packet['budget_excess_bytes']} bytes")
    if packet["budget_excess_bytes"] or any(item["status"] == "fail" for item in commands) or packet["rule_hits"]:
        return 1
    if any(item["status"] in {"timeout", "error"} for item in commands):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
