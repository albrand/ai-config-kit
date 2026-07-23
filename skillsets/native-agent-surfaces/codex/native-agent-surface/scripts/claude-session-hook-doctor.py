#!/usr/bin/env python3
"""Claude session-start hook doctor (report-only, stdlib-only).

A Claude-specific preflight that detects stale sessions and broken SessionStart
hook prerequisites before launch/resume. It is **report-only**: it never
executes an arbitrary hook command, has no repair or mutation mode, and never
writes to the user's home or plugin cache.

What it does (all read-only, all bounded by a timeout):

  * Resolves a Claude executable from an explicit override or PATH (presence
    only; discovery never executes the binary).
  * Runs only read-only CLI metadata subcommands (``--version`` and the plugin
    list) with a bounded timeout. If the CLI surface is unavailable or risky in
    your environment, supply ``--plugins-json`` and/or ``--version-string`` to
    feed the same metadata without invoking the binary.
  * For each *enabled* plugin reported, reads the on-disk
    ``<installPath>/hooks/hooks.json``, validates JSON/event shape, inspects
    SessionStart command hooks, finds exact duplicate commands within the
    event, tokenizes commands with ``shlex`` (no shell execution), verifies the
    command runtime exists, resolves literal ``${CLAUDE_PLUGIN_ROOT}`` /
    ``$CLAUDE_PLUGIN_ROOT`` references against the reported plugin installPath,
    keeps resolved targets inside that root, and verifies those targets exist.
  * Detects active Claude processes with a portable best-effort ``ps`` probe and
    compares process start times against the mtimes of the resolved Claude
    executable and the enabled plugin hook manifests. A process older than an
    updated artifact produces a ``restart_required`` advisory. It never claims
    the in-memory process version.

Hard invariants (do not weaken):

  * Never serialize environment *values* (no ``CMUX_*``, no ``PATH`` values).
  * No ``shell=True``; no interpolation of captured command text into a shell.
    Captured command strings are untrusted.
  * No repair, no mutation, no arbitrary hook execution.

Output (``--format json``, default) is a single JSON object on stdout whose
``summary`` distinguishes ``healthy`` / ``warnings`` / ``errors`` counts and a
``restart_required`` flag. Exit nonzero only for errors (a restart advisory
alone stays exit 0 unless ``--strict`` is given).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

SCHEMA_VERSION = 1
DEFAULT_TIMEOUT = 8
MAX_CAPTURE_BYTES = 1024 * 1024
MAX_INPUT_BYTES = 1024 * 1024
MAX_PLUGINS = 1024
MIN_CLAUDE_VERSION = (2, 1, 211)

# Environment variable names/prefixes that must NEVER be serialized or forwarded.
# Shared by every native-surface adapter; the doctor honors the same boundary.
DENY_ENV_NAMES = ("CMUX_SOCKET_CAPABILITY",)
DENY_ENV_PREFIXES = ("CMUX_",)
SAFE_CHILD_ENV_NAMES = (
    "HOME",
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "CLAUDE_CONFIG_DIR",
)

SESSION_START_EVENT = "SessionStart"
HOOKS_REL = "hooks/hooks.json"

# Read-only metadata subcommands run against the resolved Claude binary. These
# are the ONLY subprocess invocations the doctor performs, each with a bounded
# timeout; they must remain read-only metadata queries. If the Claude CLI
# changes its metadata surface, supply --plugins-json / --version-string instead
# of editing these.
VERSION_SUBCOMMAND = ["--version"]
PLUGIN_LIST_SUBCOMMAND = ["plugin", "list", "--json"]

# Portable best-effort process probe. Headerless columns via the ``=`` suffix
# (POSIX ps). ``lstart`` is a multi-word timestamp; see _parse_lstart.
PS_COMMAND = ["ps", "-eo", "pid=,lstart=,command="]

VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)?")
LSTART_FMT = "%a %b %d %H:%M:%S %Y"


class DoctorError(Exception):
    """Operational doctor failure (bad override input, unrecoverable)."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _deny_block() -> dict[str, Any]:
    return {
        "env_values_serialized": False,
        "denied_names": list(DENY_ENV_NAMES),
        "denied_prefixes": list(DENY_ENV_PREFIXES),
        "policy": "Environment values are never serialized. Child metadata "
        "commands receive an allowlisted environment; "
        "CMUX_SOCKET_CAPABILITY and any CMUX_* value are never forwarded.",
    }


def _child_env() -> dict[str, str]:
    """Minimal metadata-command environment; never forwards CMUX_* or secrets."""
    return {
        name: os.environ[name]
        for name in SAFE_CHILD_ENV_NAMES
        if name in os.environ
        and name not in DENY_ENV_NAMES
        and not any(name.startswith(prefix) for prefix in DENY_ENV_PREFIXES)
    }


def _read_limited(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_INPUT_BYTES + 1)
    except OSError:
        raise
    if len(raw) > MAX_INPUT_BYTES:
        raise DoctorError(
            f"input exceeds {MAX_INPUT_BYTES} byte limit: {path}"
        )
    return raw.decode("utf-8", "replace")


# --------------------------------------------------------------------------- #
# Subprocess (no shell, bounded)
# --------------------------------------------------------------------------- #
def _run_argv(argv: list[str], timeout: float) -> tuple[int, str, str]:
    """Run argv (no shell) with a bounded timeout. Returns (rc, out, err).

    Captures output defensively; never raises on non-zero/timeout (callers
    decide). Treats all captured text as untrusted.
    """
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_child_env(),
        )
    except FileNotFoundError:
        return 127, "", f"executable not found: {argv[0]!r}"
    except OSError as exc:
        return 126, "", f"os error: {exc}"

    captured: dict[str, tuple[bytes, bool]] = {}

    def drain(name: str, stream: Any) -> None:
        kept = bytearray()
        exceeded = False
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            remaining = MAX_CAPTURE_BYTES - len(kept)
            if remaining > 0:
                kept.extend(chunk[:remaining])
            if len(chunk) > max(remaining, 0):
                exceeded = True
        captured[name] = (bytes(kept), exceeded)

    assert proc.stdout is not None and proc.stderr is not None
    threads = [
        threading.Thread(target=drain, args=("stdout", proc.stdout), daemon=True),
        threading.Thread(target=drain, args=("stderr", proc.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        rc = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        for thread in threads:
            thread.join()
        proc.stdout.close()
        proc.stderr.close()
        return 124, "", f"timeout after {timeout}s"
    for thread in threads:
        thread.join()
    proc.stdout.close()
    proc.stderr.close()
    out_raw, out_exceeded = captured.get("stdout", (b"", False))
    err_raw, err_exceeded = captured.get("stderr", (b"", False))
    if out_exceeded or err_exceeded:
        return 125, "", f"output exceeds {MAX_CAPTURE_BYTES} byte limit"
    return (
        rc,
        out_raw.decode("utf-8", "replace"),
        err_raw.decode("utf-8", "replace"),
    )


# --------------------------------------------------------------------------- #
# Claude binary + metadata
# --------------------------------------------------------------------------- #
def resolve_claude(override: str | None) -> str | None:
    """Resolve the Claude binary from an override or PATH (no execution)."""
    if override:
        opath = Path(override)
        if not opath.is_absolute():
            raise DoctorError(f"--claude must be an absolute path: {override!r}")
        if not opath.is_file():
            raise DoctorError(f"--claude is not a regular file: {override!r}")
        return str(opath)
    return shutil.which("claude") or None


def query_version(claude_path: str | None, timeout: float,
                  override: str | None) -> tuple[str | None, str]:
    if override:
        return override, "override"
    if not claude_path:
        return None, "unknown"
    rc, out, _err = _run_argv([claude_path, *VERSION_SUBCOMMAND], timeout)
    if rc != 0:
        return None, "unknown"
    m = VERSION_RE.search(out)
    return (m.group(0) if m else out.strip() or None), "cli"


def version_issue(version: str | None) -> dict[str, Any] | None:
    if not version:
        return _issue(
            "error",
            "claude-version-unavailable",
            "Claude version could not be verified",
        )
    match = VERSION_RE.search(version)
    if not match:
        return _issue(
            "error",
            "claude-version-malformed",
            "Claude version is not parseable",
        )
    parts = tuple(int(part) for part in match.group(0).split("."))
    normalized = parts + (0,) * (3 - len(parts))
    if normalized < MIN_CLAUDE_VERSION:
        minimum = ".".join(str(part) for part in MIN_CLAUDE_VERSION)
        return _issue(
            "error",
            "claude-version-stale",
            f"Claude {match.group(0)} is older than required {minimum}",
        )
    return None


def _load_plugins_override(spec: str) -> list[dict[str, Any]]:
    if spec == "-":
        raw_bytes = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw_bytes) > MAX_INPUT_BYTES:
            raise DoctorError(
                f"stdin exceeds {MAX_INPUT_BYTES} byte limit"
            )
        raw = raw_bytes.decode("utf-8", "replace")
    else:
        raw = _read_limited(Path(spec))
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise DoctorError(f"--plugins-json is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise DoctorError("--plugins-json must be a JSON array of plugin objects")
    if len(data) > MAX_PLUGINS:
        raise DoctorError(f"plugin list exceeds {MAX_PLUGINS} entry limit")
    cleaned: list[dict[str, Any]] = []
    for entry in data:
        if isinstance(entry, dict):
            cleaned.append(entry)
    return cleaned


def query_plugins(claude_path: str | None, timeout: float,
                  plugins_json: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (plugins, warnings). Plugins are raw, untrusted metadata entries."""
    warnings: list[dict[str, Any]] = []
    if plugins_json is not None:
        return _load_plugins_override(plugins_json), warnings
    if not claude_path:
        warnings.append({"code": "plugins-cli-unavailable",
                         "severity": "error",
                         "message": "Claude binary not resolved; pass --plugins-json "
                                    "to inspect plugin hooks without invoking the CLI."})
        return [], warnings
    rc, out, err = _run_argv([claude_path, *PLUGIN_LIST_SUBCOMMAND], timeout)
    if rc != 0:
        warnings.append({"code": "plugins-cli-failed",
                         "severity": "error",
                         "message": f"plugin metadata query failed (rc={rc}); "
                                    "pass --plugins-json to supply it directly."})
        return [], warnings
    try:
        data = json.loads(out)
    except ValueError as exc:
        warnings.append({"code": "plugins-cli-malformed",
                         "severity": "error",
                         "message": f"plugin metadata was not valid JSON: {exc}"})
        return [], warnings
    if not isinstance(data, list):
        warnings.append({"code": "plugins-cli-shape",
                         "severity": "error",
                         "message": "plugin metadata was not a JSON array"})
        return [], warnings
    return [e for e in data if isinstance(e, dict)], warnings


# --------------------------------------------------------------------------- #
# Hook manifest validation
# --------------------------------------------------------------------------- #
def _issue(severity: str, code: str, message: str) -> dict[str, Any]:
    return {"severity": severity, "code": code, "message": message}


def _read_hooks_manifest(install_path: Path) -> tuple[Any | None, dict[str, Any] | None]:
    """Return (parsed_data, issue). issue is set when unreadable/malformed."""
    hooks_file = install_path / HOOKS_REL
    if not hooks_file.is_file():
        return None, None  # no hooks is legitimate for an mcp-only plugin
    try:
        raw = _read_limited(hooks_file)
    except DoctorError as exc:
        return None, _issue("error", "hooks-too-large", str(exc))
    except OSError as exc:
        return None, _issue("error", "hooks-unreadable", f"cannot read {HOOKS_REL}: {exc}")
    try:
        return json.loads(raw), None
    except ValueError as exc:
        return None, _issue("error", "hooks-malformed", f"{HOOKS_REL} is not valid JSON: {exc}")


def _events_root(data: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Normalize to the event->groups map. Returns (root, issue)."""
    if not isinstance(data, dict):
        return None, _issue("error", "hooks-shape", "hook manifest is not a JSON object")
    if isinstance(data.get("hooks"), dict):
        return data["hooks"], None
    return data, None


def _collect_event_commands(root: dict[str, Any], event: str
                             ) -> tuple[list[str], list[dict[str, Any]]]:
    """Flatten command strings for an event. Returns (commands, issues)."""
    issues: list[dict[str, Any]] = []
    groups = root.get(event)
    if groups is None:
        return [], []
    if not isinstance(groups, list):
        return [], [_issue("error", "event-shape",
                           f"{event} must be a list of matcher groups")]
    commands: list[str] = []
    for g in groups:
        if not isinstance(g, dict):
            issues.append(_issue("error", "event-shape",
                                 f"{event} group must be an object"))
            continue
        hooks = g.get("hooks")
        if not isinstance(hooks, list):
            issues.append(_issue("error", "event-shape",
                                 f"{event} group 'hooks' must be a list"))
            continue
        for h in hooks:
            if not isinstance(h, dict):
                issues.append(_issue("error", "event-shape",
                                     f"{event} hook entry must be an object"))
                continue
            if h.get("type") == "command":
                cmd = h.get("command")
                if isinstance(cmd, str):
                    commands.append(cmd)
                elif cmd is not None:
                    issues.append(_issue("error", "event-shape",
                                         f"{event} command hook 'command' must be a string"))
    return commands, issues


def _tokenize(command: str) -> tuple[list[str] | None, str | None]:
    """shlex.split without shell execution. Returns (tokens, error)."""
    try:
        return shlex.split(command), None
    except ValueError as exc:
        return None, f"could not tokenize command: {exc}"


def _looks_like_env_ref(token: str) -> bool:
    return "$" in token or "${" in token or token.startswith("%") and token.endswith("%")


def _resolve_plugin_root_tokens(
    tokens: list[str], install_path: Path
) -> tuple[list[str], list[dict[str, Any]]]:
    """Resolve only Claude's documented plugin-root variable, never env values."""
    resolved: list[str] = []
    issues: list[dict[str, Any]] = []
    root = install_path.resolve()
    raw_root = str(install_path)
    for token in tokens:
        value = token.replace("${CLAUDE_PLUGIN_ROOT}", str(root))
        value = value.replace("$CLAUDE_PLUGIN_ROOT", str(root))
        if value == raw_root or value.startswith(raw_root + os.sep):
            value = str(root) + value[len(raw_root):]
        if "CLAUDE_PLUGIN_ROOT" in value:
            issues.append(_issue(
                "error",
                "plugin-root-unresolved",
                "unsupported CLAUDE_PLUGIN_ROOT expression in hook command",
            ))
        resolved.append(value)
    return resolved, issues


def _check_runtime(tokens: list[str]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Verify the command runtime (first token) exists, or report why it cannot."""
    if not tokens:
        return None, _issue("error", "runtime-empty", "command produced no tokens")
    runtime = tokens[0]
    if _looks_like_env_ref(runtime):
        # We must not read environment values to resolve it; report unverified.
        return ({"name": runtime, "resolved": None, "present": None,
                 "env_reference": True},
                _issue("warning", "runtime-env-ref",
                       "command runtime uses an environment reference; presence "
                       "not verified (no env values are read)."))
    if "/" in runtime:  # absolute/relative path used directly
        path = Path(runtime)
        if path.is_file() and os.access(path, os.X_OK):
            return {"name": runtime, "resolved": runtime, "present": True}, None
        return None, _issue("error", "runtime-missing",
                            "command runtime path is not an executable file: "
                            f"{runtime}")
    resolved = shutil.which(runtime)
    if resolved:
        return {"name": runtime, "resolved": resolved, "present": True}, None
    return None, _issue("error", "runtime-missing",
                        f"command runtime not found on PATH: {runtime}")


def _within_root(target: Path, root: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _check_targets(tokens: list[str], install_path: Path) -> list[dict[str, Any]]:
    """Validate resolved literal path references anchored at the plugin root."""
    issues: list[dict[str, Any]] = []
    root = install_path.resolve()
    root_str = str(root)
    seen: set[str] = set()
    for tok in tokens:
        if root_str not in tok or tok in seen:
            continue
        seen.add(tok)
        candidate = tok
        if not candidate.startswith(root_str) and "=" in candidate:
            candidate = candidate.split("=", 1)[1]
        if not candidate.startswith(root_str):
            issues.append(_issue(
                "error",
                "embedded-plugin-root-unverified",
                "plugin-root path is embedded in an unsupported command token",
            ))
            continue
        target = Path(candidate)
        if not _within_root(target, root):
            issues.append(_issue("error", "target-escape",
                                 f"resolved target escapes plugin root: {candidate}"))
            continue
        if os.path.exists(candidate):
            continue
        # Walk back to the longest existing prefix; report the missing suffix.
        existing = candidate
        missing = ""
        while existing and not os.path.exists(existing):
            parent, leaf = os.path.split(existing)
            missing = (leaf + "/" + missing) if missing else leaf
            existing = parent
        issues.append(_issue("error", "target-missing",
                             f"hook target does not exist: {candidate}"))
    return issues


def validate_plugin(plugin: dict[str, Any]) -> dict[str, Any]:
    """Build a per-plugin report. Untrusted plugin metadata."""
    pid = plugin.get("id") or plugin.get("name") or "<unknown>"
    enabled = bool(plugin.get("enabled", True))
    version = plugin.get("version")
    install_raw = plugin.get("installPath") or plugin.get("install_path")

    report: dict[str, Any] = {
        "id": pid,
        "version": version if isinstance(version, str) else None,
        "enabled": enabled,
        "install_path": install_raw if isinstance(install_raw, str) else None,
        "hooks_present": False,
        "session_start": {"count": 0, "duplicates": [], "issues": []},
        "issues": [],
        "status": "skipped",
    }

    if not enabled:
        report["status"] = "skipped"
        return report
    if not isinstance(install_raw, str) or not install_raw:
        report["issues"].append(_issue("error", "install-path-missing",
                                       "enabled plugin has no installPath"))
        report["status"] = "error"
        return report
    install_path = Path(install_raw)
    if not install_path.is_absolute():
        report["issues"].append(_issue("error", "install-path-relative",
                                       f"installPath is not absolute: {install_raw}"))
        report["status"] = "error"
        return report
    if not install_path.is_dir():
        report["issues"].append(_issue("error", "install-path-missing",
                                       f"plugin installPath does not exist: {install_raw}"))
        report["status"] = "error"
        return report

    data, issue = _read_hooks_manifest(install_path)
    if issue:
        report["issues"].append(issue)
        report["status"] = "error"
        return report
    if data is None:
        report["status"] = "healthy"  # mcp-only plugin, no hooks
        return report
    report["hooks_present"] = True

    root, ev_issue = _events_root(data)
    if ev_issue:
        report["issues"].append(ev_issue)
        report["status"] = "error"
        return report
    assert isinstance(root, dict)

    commands, cmd_issues = _collect_event_commands(root, SESSION_START_EVENT)
    report["session_start"]["count"] = len(commands)
    report["issues"].extend(cmd_issues)

    # Exact duplicate commands within the SessionStart event of this plugin.
    seen: dict[str, int] = {}
    for c in commands:
        seen[c] = seen.get(c, 0) + 1
    dups = [
        hashlib.sha256(c.encode("utf-8", "replace")).hexdigest()
        for c, n in seen.items()
        if n > 1
    ]
    report["session_start"]["duplicates"] = dups
    for fingerprint in dups:
        report["issues"].append(_issue("warning", "duplicate-command",
                                       "duplicate SessionStart command "
                                       f"sha256:{fingerprint}"))

    for cmd in commands:
        toks, tok_err = _tokenize(cmd)
        if tok_err:
            report["issues"].append(_issue("error", "tokenize", tok_err))
            continue
        assert toks is not None
        resolved_toks, root_issues = _resolve_plugin_root_tokens(toks, install_path)
        report["issues"].extend(root_issues)
        runtime_name = Path(resolved_toks[0]).name.lower() if resolved_toks else ""
        shell_flags = resolved_toks[1:3]
        if runtime_name in {"sh", "bash", "dash", "ksh", "zsh"} and any(
            flag.startswith("-") and "c" in flag[1:] for flag in shell_flags
        ):
            report["issues"].append(_issue(
                "error",
                "shell-wrapper-unverified",
                "shell -c SessionStart commands are unsupported by the "
                "static preflight and cannot be reported healthy",
            ))
            continue
        _rt, rt_issue = _check_runtime(resolved_toks)
        if rt_issue:
            report["issues"].append(rt_issue)
        report["issues"].extend(_check_targets(resolved_toks, install_path))

    errs = sum(1 for i in report["issues"] if i["severity"] == "error")
    warns = sum(1 for i in report["issues"] if i["severity"] == "warning")
    report["status"] = "error" if errs else ("warning" if warns else "healthy")
    return report


# --------------------------------------------------------------------------- #
# Process probe
# --------------------------------------------------------------------------- #
def _parse_lstart(fields: list[str]) -> str | None:
    if len(fields) < 5:
        return None
    rebuilt = " ".join(fields[:5])
    try:
        datetime.strptime(rebuilt, LSTART_FMT)
        return rebuilt
    except ValueError:
        return None


def _lstart_to_ts(when: str | None) -> float | None:
    if not when:
        return None
    try:
        return datetime.strptime(when, LSTART_FMT).timestamp()
    except ValueError:
        return None


def probe_processes(claude_path: str | None, manifest_mtimes: dict[str, float],
                    timeout: float, ps_runner: Callable[[float], tuple[int, str, str]] | None
                    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Best-effort active-Claude probe. Never claims in-memory versions."""
    warnings: list[dict[str, Any]] = []
    runner = ps_runner or (lambda t: _run_argv(PS_COMMAND, t))
    rc, out, _err = runner(timeout)
    if rc != 0:
        warnings.append({"code": "ps-unavailable",
                         "severity": "warning",
                         "message": "process probe unavailable on this host"})
        return [], warnings

    needle = (Path(claude_path).name if claude_path else "claude").lower()
    latest_artifact = max(manifest_mtimes.values(), default=0.0)
    procs: list[dict[str, Any]] = []
    for line in out.splitlines():
        parts = line.split(None, 6)
        if len(parts) < 7:
            continue
        pid_s, dow, mon, day, hms, year, command = parts
        try:
            command_tokens = shlex.split(command)
        except ValueError:
            continue
        if not command_tokens or Path(command_tokens[0]).name.lower() != needle:
            continue
        try:
            pid = int(pid_s)
        except ValueError:
            continue
        lstart = _parse_lstart([dow, mon, day, hms, year])
        started_ts = _lstart_to_ts(lstart)
        restart = False
        restart_suspected = False
        identity_verified = False
        if started_ts is not None:
            process_executable = Path(command_tokens[0]).resolve()
            for artifact, mtime in manifest_mtimes.items():
                if artifact.startswith("claude:"):
                    artifact_path = Path(artifact.removeprefix("claude:")).resolve()
                    if artifact_path != process_executable:
                        continue
                    identity_verified = True
                if mtime > started_ts:
                    if identity_verified:
                        restart = True
                    else:
                        restart_suspected = True
                    break
        elif latest_artifact:
            warnings.append({"code": "process-starttime-unparsed",
                             "severity": "warning",
                             "message": f"could not parse start time for pid {pid}"})
        procs.append({
            "pid": pid,
            "started_at": lstart,
            "older_than_artifact": restart,
            "restart_required": restart,
            "restart_suspected": restart_suspected,
            "identity_verified": identity_verified,
        })
        if restart_suspected:
            warnings.append({
                "code": "process-identity-unverified",
                "severity": "warning",
                "message": f"pid {pid} may predate updated plugin hooks, but "
                           "basename-only process identity is insufficient",
            })
    return procs, warnings


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def build_report(claude_path: str | None, version: str | None, version_source: str,
                 plugins: list[dict[str, Any]], meta_warnings: list[dict[str, Any]],
                 processes: list[dict[str, Any]], proc_warnings: list[dict[str, Any]]
                 ) -> dict[str, Any]:
    plugin_reports = [validate_plugin(p) for p in plugins]
    statuses = [p["status"] for p in plugin_reports]
    errors = sum(1 for s in statuses if s == "error")
    warnings = sum(1 for s in statuses if s == "warning")
    healthy = sum(1 for s in statuses if s == "healthy")
    restart_required = any(p.get("restart_required") for p in processes)

    all_warnings = list(meta_warnings) + list(proc_warnings)
    for w in all_warnings:
        if w.get("severity") == "error":
            errors += 1
        elif w.get("severity") == "warning":
            warnings += 1

    if errors:
        overall = "error"
    elif warnings or restart_required:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "schema_version": SCHEMA_VERSION,
        "checked_at": _utc_now(),
        "claude": {
            "resolved": claude_path,
            "version": version,
            "version_source": version_source,
        },
        "plugins": plugin_reports,
        "processes": processes,
        "summary": {
            "healthy": healthy,
            "warnings": warnings,
            "errors": errors,
            "restart_required": restart_required,
            "overall": overall,
        },
        "advisories": all_warnings,
        "environment": _deny_block(),
    }


def render_text(report: dict[str, Any]) -> str:
    def safe(value: Any) -> str:
        return "".join(
            ch if ch == "\t" or ord(ch) >= 32 else "?"
            for ch in str(value)
        )

    s = report["summary"]
    cl = report["claude"]
    lines = [f"claude session-start hook doctor (schema v{report['schema_version']})",
             f"checked: {report['checked_at']}",
             f"claude: {cl['resolved'] or 'not resolved'} "
             f"(version={cl['version'] or 'unknown'}, source={cl['version_source']})",
             f"summary: {s['overall']} (healthy={s['healthy']} "
             f"warnings={s['warnings']} errors={s['errors']} "
             f"restart_required={s['restart_required']})"]
    for p in report["plugins"]:
        tag = {"healthy": "ok", "warning": "WARN", "error": "ERR",
               "skipped": "skip"}.get(p["status"], "?")
        lines.append(f"  [{tag}] {safe(p['id'])} -> {p['status']} "
                     f"(enabled={p['enabled']}, session_start={p['session_start']['count']})")
        for i in p["issues"]:
            lines.append(
                f"        {i['severity']}: {i['code']}: {safe(i['message'])}"
            )
    for pr in report["processes"]:
        if pr["restart_required"]:
            flag = "RESTART-ADVISED"
        elif pr.get("restart_suspected"):
            flag = "RESTART-SUSPECTED"
        else:
            flag = "ok"
        lines.append(f"  pid {pr['pid']} started={pr['started_at'] or '?'} -> {flag}")
    for a in report["advisories"]:
        lines.append(f"  advisory: {a['code']}: {safe(a['message'])}")
    lines.append("environment: values never serialized; denied prefixes: "
                 + ", ".join(report["environment"]["denied_prefixes"]))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Self-test (offline, temp fixtures)
# --------------------------------------------------------------------------- #
def selftest() -> int:
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="claude-doctor-selftest-"))
    # A healthy plugin with a literal-runtime SessionStart command + target.
    good = tmp / "good"
    (good / "hooks").mkdir(parents=True)
    target = good / "scripts" / "run.sh"
    target.parent.mkdir(parents=True)
    target.write_text("#!/bin/sh\necho hi\n")
    rt = shutil.which("sh") or "/bin/sh"
    (good / "hooks" / "hooks.json").write_text(json.dumps({
        "hooks": {SESSION_START_EVENT: [
            {"matcher": "", "hooks": [
                {"type": "command", "command": f"{rt} {target}", "timeout": 5}]}]}}))
    plugins = [
        {"id": "good", "enabled": True, "version": "1.0", "installPath": str(good)},
        {"id": "off", "enabled": False, "installPath": str(tmp / "nope")},
    ]
    report = build_report(None, None, "unknown", plugins, [], [], [])
    good_rep = next(p for p in report["plugins"] if p["id"] == "good")
    off_rep = next(p for p in report["plugins"] if p["id"] == "off")
    checks = [
        ("healthy plugin validates", good_rep["status"] == "healthy"),
        ("disabled plugin skipped", off_rep["status"] == "skipped"),
        ("runtime detected", good_rep["session_start"]["count"] == 1),
        ("no errors on clean pass", report["summary"]["errors"] == 0),
        ("env values never serialized",
         report["environment"]["env_values_serialized"] is False),
        ("json serializes cleanly", json.dumps(report) != ""),
    ]

    # Missing runtime + missing target.
    bad = tmp / "bad"
    (bad / "hooks").mkdir(parents=True)
    (bad / "hooks" / "hooks.json").write_text(json.dumps({
        "hooks": {SESSION_START_EVENT: [
            {"matcher": "", "hooks": [
                {"type": "command",
                 "command": f"{good}/scripts/missing.sh"}]}]}}))
    br = validate_plugin({"id": "bad", "enabled": True, "installPath": str(bad)})
    codes = {i["code"] for i in br["issues"]}
    checks.append(("missing runtime + target flagged", "runtime-missing" in codes))

    # Malformed JSON.
    ugly = tmp / "ugly"
    (ugly / "hooks").mkdir(parents=True)
    (ugly / "hooks" / "hooks.json").write_text("{not json")
    ur = validate_plugin({"id": "ugly", "enabled": True, "installPath": str(ugly)})
    checks.append(("malformed hooks flagged", ur["status"] == "error"))

    failed = 0
    for name, cond in checks:
        failed += 0 if cond else 1
        print(f"[{'ok' if cond else 'FAIL'}] {name}")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claude-session-hook-doctor.py",
        description="Report-only Claude SessionStart hook doctor.",
    )
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.add_argument("--claude", default=None,
                   help="absolute path to the Claude binary (default: PATH)")
    p.add_argument("--plugins-json", default=None, metavar="PATH|-",
                   help="read plugin metadata from a JSON file or stdin ('-') "
                        "instead of invoking the Claude CLI")
    p.add_argument("--version-string", default=None,
                   help="supply the Claude Code version instead of querying it")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                   help=f"bounded subprocess timeout in seconds "
                        f"(default {DEFAULT_TIMEOUT})")
    p.add_argument("--strict", action="store_true",
                   help="also exit nonzero when only a restart advisory is present")
    p.add_argument("--selftest", action="store_true",
                   help="run offline self-tests in a temp dir and exit")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.selftest:
        return selftest()

    try:
        claude_path = resolve_claude(args.claude)
        version, vsrc = query_version(claude_path, args.timeout, args.version_string)
        plugins, meta_warnings = query_plugins(
            claude_path, args.timeout, args.plugins_json
        )
        current_version_issue = version_issue(version)
        if current_version_issue:
            meta_warnings.append(current_version_issue)
    except (DoctorError, OSError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    manifest_mtimes: dict[str, float] = {}
    if claude_path and os.path.exists(claude_path):
        try:
            resolved_claude = Path(claude_path).resolve()
            manifest_mtimes[f"claude:{resolved_claude}"] = os.stat(
                resolved_claude
            ).st_mtime
        except OSError:
            pass
    for p in plugins:
        if isinstance(p, dict) and p.get("enabled", True):
            ip = p.get("installPath") or p.get("install_path")
            if isinstance(ip, str):
                hf = Path(ip) / HOOKS_REL
                if hf.is_file():
                    try:
                        manifest_mtimes[f"plugin:{hf.resolve()}"] = os.stat(hf).st_mtime
                    except OSError:
                        pass

    processes, proc_warnings = probe_processes(claude_path, manifest_mtimes,
                                               args.timeout, ps_runner=None)

    report = build_report(claude_path, version, vsrc, plugins,
                          meta_warnings, processes, proc_warnings)

    if args.format == "text":
        sys.stdout.write(render_text(report))
    else:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")

    summ = report["summary"]
    if summ["errors"]:
        return 1
    if args.strict and summ["restart_required"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
