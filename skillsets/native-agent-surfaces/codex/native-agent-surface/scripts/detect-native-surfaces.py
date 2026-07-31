#!/usr/bin/env python3
"""Native agent surface discovery (host-neutral, capability-first).

A *native agent surface* is the host software an agent runs in or through:
local session transports (cmux), terminal multiplexers (tmux, zellij), and
other agentic shells/harnesses. This helper discovers which surfaces are
present on the current host and reports their declared capabilities. Discovery
is presence-only: it never executes a discovered binary and never contacts the
network.

Hard invariants (do not weaken):
  * Never serialize environment *values*. Only the names of denied prefixes are
    reported, never their contents.
  * Never serialize ``CMUX_SOCKET_CAPABILITY`` or any ``CMUX_*`` value. cmux
    socket capability stays local to the host.
  * cmux is one adapter, not the universal surface. The registry is
    host-neutral; add surfaces here, do not special-case one as canonical.
  * Discovery never executes a PATH-resolved binary. Presence is not trust.

Output (``--format json``, default) is a single JSON object on stdout:

    {
      "schema_version": 1,
      "detected_at": "<iso8601 utc>",
      "host": {"sysname": "...", "machine": "..."},
      "surfaces": [ { "name": ..., "category": ..., "available": bool, ... } ],
      "environment": { "env_values_serialized": false, "denied_prefixes": [...] }
    }
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from datetime import datetime, timezone
from typing import Any, Iterable

SCHEMA_VERSION = 1

# Environment variable names/prefixes that must NEVER be serialized or forwarded.
# Mirrors the cmux-hermes broker boundary; kept here so the contract is enforced
# by every native-surface adapter, not just cmux.
DENY_ENV_NAMES = ("CMUX_SOCKET_CAPABILITY",)
DENY_ENV_PREFIXES = ("CMUX_",)

# Host-neutral registry. Each entry describes how to recognize a surface and the
# capabilities it offers when present. ``discovery_command`` is documentation
# only and is NEVER executed by this tool.
#   * ``adapter`` names the resolver adapter (scripts/resolve-workspace.py) that
#     can normalize a structured runtime inventory for reuse decisions, or null.
#   * ``runtime_capabilities`` are candidate fields the adapter can consume
#     (metadata only; presence is not a guarantee the runtime exposes them).
REGISTRY: list[dict[str, Any]] = [
    {
        "name": "cmux",
        "category": "session-transport",
        "binary_names": ["cmux"],
        "capabilities": [
            "workspace-lifecycle",
            "surface-targeting",
            "cross-surface-send",
            "id-format",
            "lifecycle-cancel-close",
        ],
        "adapter": "cmux",
        "runtime_capabilities": ["workspace-list", "workspace-cwd", "full-uuid"],
        "discovery_command": "cmux --id-format both --json list-workspaces",
        "notes": "Local UI/session transport. Persist full UUIDs; never "
        "serialize CMUX_SOCKET_CAPABILITY or any CMUX_* value.",
    },
    {
        "name": "tmux",
        "category": "terminal-multiplexer",
        "binary_names": ["tmux"],
        "capabilities": ["session-lifecycle", "pane-targeting"],
        "adapter": "tmux",
        "runtime_capabilities": ["session-cwd"],
        "discovery_command": "tmux list-sessions",
        "notes": "Generic agentic shell surface; one adapter among many. Has no "
        "workspace UUIDs; the resolver never invents capabilities it lacks.",
    },
    {
        "name": "zellij",
        "category": "terminal-multiplexer",
        "binary_names": ["zellij"],
        "capabilities": ["session-lifecycle", "pane-targeting"],
        "discovery_command": "zellij list-sessions",
        "notes": "Generic agentic shell surface.",
    },
    {
        "name": "git",
        "category": "vcs",
        "binary_names": ["git"],
        "capabilities": ["worktree-isolation", "branch-lifecycle"],
        "discovery_command": "git rev-parse --is-inside-work-tree",
        "notes": "Used by write-isolated adapters (worktrees); not a surface itself.",
    },
    {
        # Orca (the Orca coding-agent desktop app) ships a `orca` binary.
        # GNOME's screen reader is also named `orca` on Linux, so this entry is
        # gated to Darwin to avoid a presence-only collision. Discovery remains
        # PATH-presence only; the binary is never executed.
        "name": "orca",
        "category": "agent-harness",
        "binary_names": ["orca"],
        "host_platforms": ["Darwin"],
        "capabilities": [
            "workspace-lifecycle",
            "worktree-isolation",
            "surface-targeting",
            "orchestration",
            "scheduled-automations",
            "browser-control",
            "mobile-emulator-control",
            "file-mutation-ownership",
        ],
        "adapter": "orca",
        "runtime_capabilities": [
            "worktree-list",
            "worktree-cwd",
            "terminal-list",
            "automation-list",
        ],
        "discovery_command": "orca --version",
        "notes": "Orca coding-agent desktop app. Darwin-only to avoid the Linux "
        "GNOME screen-reader collision; resolve on PATH without executing. Orca "
        "owns worktree/terminal/automation/browser/emulator lifecycle.",
    },
    {
        # `orca-ide` is an alternate launcher that does not collide with the
        # GNOME screen reader; allow it cross-platform when present.
        "name": "orca-ide",
        "category": "agent-harness",
        "binary_names": ["orca-ide"],
        "capabilities": [
            "workspace-lifecycle",
            "worktree-isolation",
            "surface-targeting",
            "orchestration",
            "scheduled-automations",
            "browser-control",
            "mobile-emulator-control",
            "file-mutation-ownership",
        ],
        "adapter": "orca",
        "runtime_capabilities": [
            "worktree-list",
            "worktree-cwd",
            "terminal-list",
            "automation-list",
        ],
        "discovery_command": "orca-ide --version",
        "notes": "Alternate Orca launcher; cross-platform. Presence only; never "
        "executed. Same Orca capability surface as the `orca` entry.",
    },
]


def current_platform() -> str:
    """Return the current platform.system() value (overridable in tests)."""
    return platform.system()


def entry_platforms(entry: dict[str, Any]) -> list[str] | None:
    """Return the host_platforms allowlist for an entry, or None for all."""
    raw = entry.get("host_platforms")
    if raw is None:
        return None
    if isinstance(raw, str):
        return [raw]
    return [str(p) for p in raw]


class SurfaceError(Exception):
    """Raised for recoverable, fail-closed conditions."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def which(binary_name: str) -> str | None:
    """Resolve a binary on PATH without executing it."""
    if not binary_name or "/" in binary_name or "\\" in binary_name:
        return None
    found = shutil.which(binary_name)
    return found or None


def deny_block() -> dict[str, Any]:
    """Describe the env-hygiene boundary WITHOUT serializing any value."""
    return {
        "env_values_serialized": False,
        "denied_names": list(DENY_ENV_NAMES),
        "denied_prefixes": list(DENY_ENV_PREFIXES),
        "policy": "Environment values are never serialized or forwarded; "
        "CMUX_SOCKET_CAPABILITY and any CMUX_* value stays on the host.",
    }


def detect_surfaces(
    registry: Iterable[dict[str, Any]] = REGISTRY,
    *,
    host_platform: str | None = None,
) -> list[dict[str, Any]]:
    """Resolve each registry entry by PATH presence (never execution).

    ``host_platform`` overrides the detected platform for tests. An entry with a
    ``host_platforms`` allowlist is resolved only when the current platform is in
    that list; otherwise it is reported as unavailable with an
    ``unsupported_platform`` adapter status so callers can distinguish a
    platform-collision skip from a missing binary.
    """
    plat = host_platform or current_platform()
    results: list[dict[str, Any]] = []
    for entry in registry:
        name = str(entry["name"])
        allowed = entry_platforms(entry)
        platform_ok = allowed is None or plat in allowed
        binary_names = [str(b) for b in entry.get("binary_names", [])]
        resolved = next((b for b in (which(n) for n in binary_names) if b), None) if platform_ok else None
        available = resolved is not None
        if not platform_ok:
            adapter_status = "unsupported-platform"
        elif available and entry.get("adapter"):
            adapter_status = "ready"
        elif not available:
            adapter_status = "missing-binary"
        else:
            adapter_status = "none"
        results.append(
            {
                "name": name,
                "category": str(entry.get("category", "unknown")),
                "available": available,
                "binary": resolved,
                "version": None,
                "capabilities": list(entry.get("capabilities", [])),
                "adapter": entry.get("adapter"),
                "adapter_status": adapter_status,
                "runtime_capabilities": list(entry.get("runtime_capabilities", [])),
                "discovery_command": entry.get("discovery_command"),
                "host_platforms": allowed,
                "notes": entry.get("notes"),
            }
        )
    return results


def build_report(*, host_platform: str | None = None) -> dict[str, Any]:
    plat = host_platform or current_platform()
    return {
        "schema_version": SCHEMA_VERSION,
        "detected_at": _utc_now(),
        "host": {
            "sysname": plat,
            "machine": platform.machine(),
        },
        "surfaces": detect_surfaces(host_platform=plat),
        "environment": deny_block(),
    }


def render_text(report: dict[str, Any]) -> str:
    lines = [f"native agent surfaces (schema v{report['schema_version']})"]
    lines.append(f"detected: {report['detected_at']} on "
                 f"{report['host']['sysname']}/{report['host']['machine']}")
    for s in report["surfaces"]:
        mark = "+" if s["available"] else "-"
        lines.append(f"  [{mark}] {s['name']:<10} {s['category']:<20} "
                     f"{s['binary'] or 'not found'}"
                     + (f"  ({s['version']})" if s["version"] else ""))
        if s["available"]:
            lines.append(f"        capabilities: {', '.join(s['capabilities'])}")
        lines.append(f"        discovery: {s['discovery_command']}")
    env = report["environment"]
    lines.append("environment: values never serialized; denied prefixes: "
                 + ", ".join(env["denied_prefixes"]))
    return "\n".join(lines) + "\n"


def selftest() -> int:
    """Offline self-test using a fake bin dir on PATH. No network, no writes."""
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp(prefix="native-surface-test-"))
    bindir = tmp / "bin"
    bindir.mkdir()
    fake = bindir / "cmux"
    marker = tmp / "executed"
    fake.write_text(f"#!/bin/sh\ntouch {marker}\n")
    os.chmod(fake, 0o755)

    # Fake `orca` and `orca-ide` binaries on PATH to prove the Darwin entry is
    # detected by presence only (never executed), and that the same binary is
    # NOT selected as plain `orca` on Linux (GNOME screen-reader collision).
    orca_marker = tmp / "orca-executed"
    orca_fake = bindir / "orca"
    orca_fake.write_text(f"#!/bin/sh\ntouch {orca_marker}\n")
    os.chmod(orca_fake, 0o755)
    orca_ide_fake = bindir / "orca-ide"
    orca_ide_fake.write_text("#!/bin/sh\ntrue\n")
    os.chmod(orca_ide_fake, 0o755)

    saved_path = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{bindir}:{saved_path}"
    try:
        report = build_report()
        cmux = next(s for s in report["surfaces"] if s["name"] == "cmux")

        # Simulated Darwin: `orca` should be detected by presence and not executed.
        darwin_report = build_report(host_platform="Darwin")
        orca_darwin = next(s for s in darwin_report["surfaces"] if s["name"] == "orca")
        orca_ide_darwin = next(s for s in darwin_report["surfaces"] if s["name"] == "orca-ide")

        # Simulated Linux: `orca` must NOT be selected (GNOME screen-reader
        # collision); `orca-ide` may still qualify cross-platform.
        linux_report = build_report(host_platform="Linux")
        orca_linux = next(s for s in linux_report["surfaces"] if s["name"] == "orca")
        orca_ide_linux = next(s for s in linux_report["surfaces"] if s["name"] == "orca-ide")

        checks = [
            ("cmux detected via fake bin", cmux["available"] is True),
            ("PATH binary was not executed", not marker.exists()),
            ("env values never serialized", report["environment"]["env_values_serialized"] is False),
            ("deny block lists CMUX_ prefix", "CMUX_" in report["environment"]["denied_prefixes"]),
            ("host-neutral registry has >1 surface", len(report["surfaces"]) > 1),
            ("adapter_status never serializes env values",
             all("env" not in str(s) for s in report["surfaces"])),
            ("cmux exposes runtime_capabilities",
             bool(cmux.get("runtime_capabilities"))),
            ("json serializes cleanly", json.dumps(report) != ""),
            ("orca detected on Darwin by presence", orca_darwin["available"] is True),
            ("orca binary never executed on Darwin", not orca_marker.exists()),
            ("orca adapter_status ready on Darwin", orca_darwin["adapter_status"] == "ready"),
            ("orca declares worktree-isolation capability",
             "worktree-isolation" in orca_darwin["capabilities"]),
            ("orca declares scheduled-automations capability",
             "scheduled-automations" in orca_darwin["capabilities"]),
            ("orca-ide detected on Darwin", orca_ide_darwin["available"] is True),
            ("orca NOT selected on Linux (screen-reader collision)",
             orca_linux["available"] is False),
            ("orca unsupported-platform on Linux",
             orca_linux["adapter_status"] == "unsupported-platform"),
            ("orca-ide still detected on Linux", orca_ide_linux["available"] is True),
            ("report carries host_platforms metadata for orca",
             "Darwin" in (orca_darwin.get("host_platforms") or [])),
        ]
        failed = 0
        for name, cond in checks:
            failed += 0 if cond else 1
            print(f"[{'ok' if cond else 'FAIL'}] {name}")
        print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
        return 1 if failed else 0
    finally:
        os.environ["PATH"] = saved_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="detect-native-surfaces.py",
        description="Discover native agent surfaces (capability-first, host-neutral).",
    )
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument("--check", metavar="NAME",
                        help="exit 0 only if surface NAME is available, else 1")
    parser.add_argument("--selftest", action="store_true",
                        help="run offline self-tests in a temp dir and exit")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    report = build_report()

    if args.check:
        wanted = args.check.strip().lower()
        hit = next((s for s in report["surfaces"] if s["name"] == wanted), None)
        return 0 if (hit and hit["available"]) else 1

    if args.format == "text":
        sys.stdout.write(render_text(report))
    else:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
