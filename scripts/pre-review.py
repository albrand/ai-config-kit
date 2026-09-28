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
import shutil
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


PACKET_BUDGET = 64 * 1024
OUTPUT_TAIL_BUDGET = 4 * 1024
DEFAULT_BASE = "origin/main"
MIN_FREE_BYTES = 20 * 1024**3
TYPESCRIPT_SUFFIXES = {".ts", ".tsx", ".mts", ".cts"}
JAVASCRIPT_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs"}
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
    return subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=timeout, check=False, shell=False, env=env)


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


def record_command(name: str, argv: list[str], repo: Path, *, timeout: float = 120,
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


def related_test_paths(repo: Path, paths: list[str]) -> list[str]:
    changed = {Path(path) for path in paths}
    tests = {path for path in paths if re.search(r"(?:^|/)(?:test[^/]*|[^/]*\.(?:test|spec)\.[^.]+)$", path)}
    source_stems = {test_stem(path) for path in changed if path.suffix in ({".py"} | TYPESCRIPT_SUFFIXES | JAVASCRIPT_SUFFIXES)}
    tracked_paths = nul_paths(git_output(repo, "ls-files", "-z"))
    candidates = tracked_paths | set(paths)
    ignored_parts = {".git", "node_modules", ".venv", "venv", "dist", "build", "coverage"}
    for rel in candidates:
        if any(part in ignored_parts for part in Path(rel).parts):
            continue
        candidate = Path(rel)
        if re.search(r"(?:^|/)(?:test[^/]*|[^/]*\.(?:test|spec)\.[^.]+)$", rel) and test_stem(candidate) in source_stems:
            tests.add(rel)
    return sorted(tests)


def focused_test_commands(repo: Path, tests: list[str], output_dir: Path,
                          skip_tests: bool = False) -> list[tuple[str, list[str], str | None]]:
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
        pytest = binary_path(repo, "pytest")
        if pytest:
            commands.append(("focused-python-tests", [pytest, *absolute_python], None))
        elif all("unittest.main(" in (repo / path).read_text(encoding="utf-8", errors="replace") for path in python_tests):
            commands.append(("focused-python-tests", [sys.executable, *absolute_python], None))
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


def builtin_rule_scan(repo: Path, paths: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    scanned = 0
    for rel in paths:
        path = Path(rel)
        if path.suffix.lower() not in ({".py", ".yml", ".yaml"} | TYPESCRIPT_SUFFIXES | JAVASCRIPT_SUFFIXES):
            continue
        target = (repo / path).resolve()
        try:
            target.relative_to(repo)
            source = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            continue
        scanned += 1
        if path.suffix.lower() == ".py":
            hits.extend(python_digit_rule(rel, source))
        if path.suffix.lower() in {".yml", ".yaml"} and (".github/workflows/" in f"/{rel}" or rel.startswith(".github/workflows/")):
            token_use = bool(re.search(r"(?:secrets\.GITHUB_TOKEN|\bGH_TOKEN\b)", source))
            permission_declared = bool(re.search(r"(?m)^\s*permissions\s*:", source))
            if token_use and not permission_declared:
                hits.append({"rule_id": "pre_review.github_token_permissions", "path": rel,
                             "line": 1, "message": "workflow uses the GitHub token without declaring permissions"})
        if path.suffix.lower() in (TYPESCRIPT_SUFFIXES | JAVASCRIPT_SUFFIXES):
            for match in re.finditer(r"(?m)^\s*(Promise\.(?:resolve|reject)\s*\([^;\n]*\))\s*;", source):
                line = source.count("\n", 0, match.start()) + 1
                hits.append({"rule_id": "pre_review.no_floating_promises", "path": rel,
                             "line": line, "message": "Promise expression is neither awaited nor returned"})
            for match in re.finditer(
                r"(?:const|let|var)\s+(\w+)\s*=\s*new\s+URL\s*\(\s*(\w+)\s*\)[\s\S]{0,1200}?\1\s*\.\s*hostname[\s\S]{0,1200}?\b(?:Pool|Client)\s*\(\s*\{[\s\S]{0,500}?connectionString\s*:\s*\2\b",
                source,
            ):
                line = source.count("\n", 0, match.start()) + 1
                hits.append({"rule_id": "pre_review.url_parser_mismatch", "path": rel,
                             "line": line, "message": "WHATWG URL hostname vetting precedes use of the same value by a database client"})
    check = {"name": "built-in-rule-scan", "command": ["pre-review built-in rules", *paths],
             "status": "fail" if hits else "pass", "exit_code": 1 if hits else 0,
             "output_tail": f"scanned {scanned} changed source/config file(s); {len(hits)} hit(s)",
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

    def run_check(name: str, argv: list[str], *, timeout: float = 120,
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
    active_rule_files: list[Path] = []
    project_rules = project_rule_files(repo)
    source_paths = [path for path in paths if Path(path).suffix.lower() in ({".py", ".c", ".h", ".go", ".java", ".yaml", ".yml"} | TYPESCRIPT_SUFFIXES | JAVASCRIPT_SUFFIXES)]
    if source_paths:
        if semgrep:
            active_rule_files = [starter_rules_path(), *project_rules]
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
    commands.extend(run_check(name, argv, skip_reason=reason,
                              requires_hydration=name in {"focused-playwright-tests", "focused-typescript-tests",
                                                          "focused-node-tests"})
                    for name, argv, reason in focused_test_commands(repo, tests, output_dir, args.skip_tests))

    # Keep rule IDs stable and avoid reporting the same finding from both the
    # built-in safety net and Semgrep.
    unique_hits: dict[tuple[Any, ...], dict[str, Any]] = {}
    for hit in hits:
        key = (hit.get("rule_id"), hit.get("path"), hit.get("line"), hit.get("message"))
        unique_hits[key] = hit
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
