#!/usr/bin/env python3
"""Attach an Orca-owned terminal to the bounded Hermes master over Tailscale.

This bridge uses a fixed forward-SSH command shape, validates every variable
token, clears SSH environment forwarding, and never invokes a local shell.
The remote process runs as the restricted ``hermes`` user inside tmux.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys

REMOTE_USER = "hermes"
REMOTE_HOME = "/var/lib/hermes"
TMUX_TMPDIR = "/var/lib/hermes/.tmux"
HERMES_BIN = "/opt/hermes/agent/venv/bin/hermes"
SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}$")


def build_ssh_argv(target: str, session: str) -> list[str]:
    if not TARGET_RE.fullmatch(target):
        raise ValueError("invalid SSH target alias")
    if not SESSION_RE.fullmatch(session):
        raise ValueError("invalid tmux session name")
    return [
        "ssh",
        "-tt",
        "-o", "BatchMode=yes",
        "-o", "ClearAllForwardings=yes",
        target,
        "--",
        "sudo", "-n", "-u", REMOTE_USER,
        "env",
        f"HOME={REMOTE_HOME}",
        f"TMUX_TMPDIR={TMUX_TMPDIR}",
        "TERM=xterm-256color",
        "COLORTERM=truecolor",
        "tmux", "new-session", "-A",
        "-s", session,
        "-c", REMOTE_HOME,
        HERMES_BIN, "chat", "--cli",
    ]


def sanitized_ssh_environment(
    ssh_config: str,
    environ: dict[str, str],
) -> dict[str, str]:
    """Remove everything selected by SendEnv; reject configured SetEnv."""
    send_patterns: list[str] = []
    for raw_line in ssh_config.splitlines():
        key, _, value = raw_line.strip().partition(" ")
        if key.lower() == "setenv" and value.strip():
            raise ValueError("SSH target config uses SetEnv; refusing connection")
        if key.lower() == "sendenv":
            send_patterns.extend(value.split())

    cleaned = dict(environ)
    for name in list(cleaned):
        if name.startswith("CMUX_") or any(
            fnmatch.fnmatchcase(name, pattern)
            for pattern in send_patterns
            if not pattern.startswith("-")
        ):
            cleaned.pop(name, None)
    return cleaned


def resolved_ssh_environment(target: str) -> dict[str, str]:
    probe = subprocess.run(
        ["ssh", "-G", target],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return sanitized_ssh_environment(probe.stdout, dict(os.environ))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Attach an Orca terminal to a restricted Hermes tmux master."
    )
    parser.add_argument("--target", default="vps", help="validated SSH alias")
    parser.add_argument("--name", required=True, help="validated tmux session name")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        command = build_ssh_argv(args.target, args.name)
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    try:
        environment = resolved_ssh_environment(args.target)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        sys.stderr.write(f"error: unsafe or unreadable SSH config: {exc}\n")
        return 2
    os.execvpe(command[0], command, environment)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
