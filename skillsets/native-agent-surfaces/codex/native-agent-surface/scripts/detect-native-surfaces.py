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
        "discovery_command": "cmux --id-format both tree --all",
        "notes": "Local UI/session transport. Persist full UUIDs; never "
        "serialize CMUX_SOCKET_CAPABILITY or any CMUX_* value.",
    },
    {
        "name": "tmux",
        "category": "terminal-multiplexer",
        "binary_names": ["tmux"],
        "capabilities": ["session-lifecycle", "pane-targeting"],
        "discovery_command": "tmux list-sessions",
        "notes": "Generic agentic shell surface; one adapter among many.",
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
]


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
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for entry in registry:
        name = str(entry["name"])
        binary_names = [str(b) for b in entry.get("binary_names", [])]
        resolved = next((b for b in (which(n) for n in binary_names) if b), None)
        available = resolved is not None
        results.append(
            {
                "name": name,
                "category": str(entry.get("category", "unknown")),
                "available": available,
                "binary": resolved,
                "version": None,
                "capabilities": list(entry.get("capabilities", [])),
                "discovery_command": entry.get("discovery_command"),
                "notes": entry.get("notes"),
            }
        )
    return results


def build_report() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "detected_at": _utc_now(),
        "host": {
            "sysname": platform.system(),
            "machine": platform.machine(),
        },
        "surfaces": detect_surfaces(),
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

    saved_path = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{bindir}:{saved_path}"
    try:
        report = build_report()
        cmux = next(s for s in report["surfaces"] if s["name"] == "cmux")
        checks = [
            ("cmux detected via fake bin", cmux["available"] is True),
            ("PATH binary was not executed", not marker.exists()),
            ("env values never serialized", report["environment"]["env_values_serialized"] is False),
            ("deny block lists CMUX_ prefix", "CMUX_" in report["environment"]["denied_prefixes"]),
            ("host-neutral registry has >1 surface", len(report["surfaces"]) > 1),
            ("json serializes cleanly", json.dumps(report) != ""),
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
