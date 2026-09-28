#!/usr/bin/env python3
"""Run the repository's available deterministic checks and emit a bounded packet."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


PACKET_BUDGET = 64 * 1024
OUTPUT_TAIL_BUDGET = 4 * 1024
DEFAULT_BASE = "origin/main"
TYPESCRIPT_SUFFIXES = {".ts", ".tsx", ".mts", ".cts"}
JAVASCRIPT_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs"}
STARTER_RULES = Path(__file__).resolve().parents[1] / "skillsets" / "pr-review" / "semgrep" / "pre-review.yml"


class PreReviewError(Exception):
    """An unrecoverable pre-review setup error."""


def run_capture(argv: list[str], cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=timeout, check=False, shell=False)


def output_tail(raw: bytes) -> str:
    return raw[-OUTPUT_TAIL_BUDGET:].decode("utf-8", errors="replace")


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


def resolve_base(repo: Path, requested: str | None) -> tuple[str, str, str]:
    ref = requested or DEFAULT_BASE
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


def changed_paths(repo: Path, merge_base: str, output_dir: Path) -> tuple[list[str], bool, int]:
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
    paths = sorted(path for path in (nul_paths(committed) | nul_paths(working) | nul_paths(untracked)) if included(path))
    committed_diff = git_output(repo, "diff", "--binary", f"{merge_base}..HEAD", "--")
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
    return paths, dirty, len(committed_diff) + len(working_diff) + untracked_diff_bytes


def binary_path(repo: Path, name: str) -> str | None:
    local = repo / "node_modules" / ".bin" / name
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return shutil.which(name)


def record_command(name: str, argv: list[str], repo: Path, *, timeout: int = 120,
                   skip_reason: str | None = None) -> dict[str, Any]:
    command = {"name": name, "command": argv, "status": "not-run", "exit_code": None,
               "output_tail": ""}
    if skip_reason:
        command.update(status="skip", output_tail=skip_reason)
        return command
    try:
        result = run_capture(argv, repo, timeout=timeout)
        tail = output_tail(result.stdout).replace(str(repo), "<repo>")
        command.update(status="pass" if result.returncode == 0 else "fail",
                       exit_code=result.returncode, output_tail=tail)
    except FileNotFoundError:
        command.update(status="skip", output_tail="not installed")
    except subprocess.TimeoutExpired as error:
        raw = error.stdout or b""
        if isinstance(raw, str):
            raw = raw.encode("utf-8", errors="replace")
        command.update(status="fail", output_tail=(output_tail(raw) + "\ncommand timed out" ).strip())
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


def focused_test_commands(repo: Path, tests: list[str], skip_tests: bool = False) -> list[tuple[str, list[str], str | None]]:
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
    if Path(path).name.lower().find("date") < 0 and not re.search(r"\b(date|day|month|year|timestamp)\b", source, re.I):
        return []
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []
    hits: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name) or func.value.id != "re":
            continue
        if func.attr not in {"compile", "match", "fullmatch", "search"}:
            continue
        try:
            pattern = ast.literal_eval(node.args[0])
        except (ValueError, TypeError):
            continue
        if not isinstance(pattern, str) or r"\d" not in pattern:
            continue
        flags: ast.AST | None = None
        if func.attr == "compile" and len(node.args) > 1:
            flags = node.args[1]
        for keyword in node.keywords:
            if keyword.arg == "flags":
                flags = keyword.value
        flag_text = ast.dump(flags) if flags is not None else ""
        if "ASCII" not in flag_text and not re.search(r"\bA\b", flag_text):
            hits.append({"rule_id": "pre_review.python_unicode_digits", "path": path,
                         "line": node.lineno, "message": r"date or identifier regex uses \d without re.ASCII"})
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
             "output_tail": f"scanned {scanned} changed source/config file(s); {len(hits)} hit(s)"}
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
             f"- Dirty: `{str(packet['dirty']).lower()}`", f"- Changed paths: {packet['changed_path_count']}",
             f"- Raw diff bytes: {packet['raw_diff_bytes']}", f"- Packet bytes: {packet['packet_bytes']} / {packet['packet_budget_bytes']}",
             "", "## Checks", ""]
    for command in packet["commands"]:
        lines.append(f"- `{command['name']}`: **{command['status']}** (exit {command['exit_code']}); {command['output_tail'][:240]}")
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
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository directory (default: current directory)")
    parser.add_argument("--output-dir", type=Path, default=Path(".pre-review"), help="packet directory (default: .pre-review)")
    parser.add_argument("--skip-tests", action="store_true",
                        help="record focused tests as skipped without running them (default: focused tests enabled)")
    parser.add_argument("--skip-repo-lint", action="store_true",
                        help="record the repository lint script as skipped without running it")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        repo = resolve_repo(args.repo.resolve())
        base_ref, base_sha, merge_sha = resolve_base(repo, args.base)
        output_dir = args.output_dir if args.output_dir.is_absolute() else repo / args.output_dir
        paths, dirty, raw_diff_bytes = changed_paths(repo, merge_sha, output_dir)
    except PreReviewError as error:
        print(f"pre-review: {error}", file=sys.stderr)
        return 2

    head_sha = os.fsdecode(git_output(repo, "rev-parse", "HEAD").strip())
    commands: list[dict[str, Any]] = []
    hits, built_in = builtin_rule_scan(repo, paths)
    commands.append(built_in)

    package, manager = package_metadata(repo)
    has_ts = any(Path(path).suffix.lower() in TYPESCRIPT_SUFFIXES for path in paths)
    has_py = any(Path(path).suffix.lower() == ".py" for path in paths)
    has_md = any(Path(path).suffix.lower() in {".md", ".markdown"} for path in paths)
    workflows = [path for path in paths if path.startswith(".github/workflows/") and Path(path).suffix.lower() in {".yml", ".yaml"}]

    typecheck = package_script(package, manager, ("typecheck", "type-check", "check:types"))
    if typecheck:
        commands.append(record_command("repo-typecheck", typecheck, repo))
    elif (repo / "tsconfig.json").is_file():
        tsc = binary_path(repo, "tsc")
        commands.append(record_command("typescript-typecheck", [tsc, "--noEmit", "--incremental", "false"] if tsc else [], repo,
                                       skip_reason=None if tsc else "tsc not installed"))
    elif has_ts:
        commands.append(record_command("typescript-typecheck", [], repo, skip_reason="no configured TypeScript project"))

    if has_py and has_mypy_config(repo):
        mypy = binary_path(repo, "mypy")
        python_files = [path for path in paths if path.endswith(".py")]
        commands.append(record_command("python-mypy", [mypy, *command_paths(repo, python_files)] if mypy else [], repo,
                                       skip_reason=None if mypy else "mypy not installed"))

    lint = package_script(package, manager, ("lint", "lint:check", "check:lint"))
    if lint:
        commands.append(record_command("repo-lint", lint, repo,
                                       skip_reason="skipped by --skip-repo-lint" if args.skip_repo_lint else None))

    if has_ts:
        eslint = binary_path(repo, "eslint")
        config_present = any((repo / name).exists() for name in ("eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml"))
        ts_files = [path for path in paths if Path(path).suffix.lower() in TYPESCRIPT_SUFFIXES]
        if eslint and config_present:
            commands.append(record_command("eslint-no-floating-promises", [eslint, "--rule", "@typescript-eslint/no-floating-promises:error", *command_paths(repo, ts_files)], repo))
        else:
            reason = "eslint not installed" if not eslint else "no configured eslint project"
            commands.append(record_command("eslint-no-floating-promises", [], repo, skip_reason=reason))

    if workflows:
        actionlint = binary_path(repo, "actionlint")
        commands.append(record_command("actionlint", [actionlint, *command_paths(repo, workflows)] if actionlint else [], repo,
                                       skip_reason=None if actionlint else "actionlint not installed"))

    if has_md:
        markdownlint = binary_path(repo, "markdownlint-cli2") or binary_path(repo, "markdownlint")
        markdown_files = [path for path in paths if Path(path).suffix.lower() in {".md", ".markdown"}]
        commands.append(record_command("markdownlint", [markdownlint, *command_paths(repo, markdown_files)] if markdownlint else [], repo,
                                       skip_reason=None if markdownlint else "markdownlint not installed"))

    semgrep = binary_path(repo, "semgrep")
    active_rule_files: list[Path] = []
    project_rules = project_rule_files(repo)
    source_paths = [path for path in paths if Path(path).suffix.lower() in ({".py", ".c", ".h", ".go", ".java", ".yaml", ".yml"} | TYPESCRIPT_SUFFIXES | JAVASCRIPT_SUFFIXES)]
    if source_paths:
        if semgrep:
            active_rule_files = [STARTER_RULES, *project_rules]
            semgrep_args = [semgrep, "scan", "--json", "--error"]
            for rule_file in active_rule_files:
                semgrep_args.extend(["--config", str(rule_file)])
            semgrep_args.extend(command_paths(repo, source_paths))
            try:
                semgrep_run = run_capture(semgrep_args, repo, timeout=180)
                hits.extend(semgrep_result(semgrep_run.stdout, repo))
                commands.append({"name": "semgrep", "command": semgrep_args,
                                 "status": "fail" if semgrep_run.returncode else "pass",
                                 "exit_code": semgrep_run.returncode,
                                 "output_tail": output_tail(semgrep_run.stdout).replace(str(repo), "<repo>")})
            except subprocess.TimeoutExpired as error:
                raw = error.stdout or b""
                if isinstance(raw, str):
                    raw = raw.encode("utf-8", errors="replace")
                commands.append({"name": "semgrep", "command": semgrep_args, "status": "fail",
                                 "exit_code": None, "output_tail": (output_tail(raw) + "\ncommand timed out").strip()})
        else:
            commands.append(record_command("semgrep", [], repo, skip_reason="semgrep not installed"))

    tests = related_test_paths(repo, paths)
    commands.extend(record_command(name, argv, repo, skip_reason=reason)
                    for name, argv, reason in focused_test_commands(repo, tests, args.skip_tests))

    # Keep rule IDs stable and avoid reporting the same finding from both the
    # built-in safety net and Semgrep.
    unique_hits: dict[tuple[Any, ...], dict[str, Any]] = {}
    for hit in hits:
        key = (hit.get("rule_id"), hit.get("path"), hit.get("line"), hit.get("message"))
        unique_hits[key] = hit
    packet = {
        "schema_version": 1,
        "repo": str(repo),
        "head_sha": head_sha,
        "base": {"ref": base_ref, "sha": base_sha, "merge_base_sha": merge_sha},
        "dirty": dirty,
        "changed_paths": paths,
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
    return 1 if packet["budget_excess_bytes"] or any(item["status"] == "fail" for item in commands) or packet["rule_hits"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
