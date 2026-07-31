#!/usr/bin/env python3
"""Offline argv-contract tests for the Orca-to-Hermes terminal bridge."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MODULE_PATH = (
    SCRIPT_DIR.parent
    / "codex"
    / "orca-workflow-automation"
    / "scripts"
    / "orca-hermes-terminal.py"
)
SPEC = importlib.util.spec_from_file_location("orca_hermes_terminal", MODULE_PATH)
bridge = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(bridge)


class BridgeArgvTest(unittest.TestCase):
    def test_fixed_forward_ssh_shape(self):
        argv = bridge.build_ssh_argv("vps", "orca-hermes-master")
        self.assertEqual(argv[0], "ssh")
        self.assertIn("BatchMode=yes", argv)
        self.assertIn("ClearAllForwardings=yes", argv)
        self.assertEqual(argv.count("vps"), 1)
        self.assertIn("sudo", argv)
        self.assertIn("hermes", argv)
        self.assertIn("tmux", argv)
        self.assertIn("/opt/hermes/agent/venv/bin/hermes", argv)
        self.assertIn("TERM=xterm-256color", argv)
        self.assertIn("COLORTERM=truecolor", argv)
        self.assertNotIn("sh", argv)
        self.assertNotIn("-c", argv[: argv.index("vps")])

    def test_rejects_shell_metacharacters_and_whitespace(self):
        for target in ("vps;id", "vps host", "$(id)"):
            with self.assertRaises(ValueError):
                bridge.build_ssh_argv(target, "safe")
        for session in ("bad;id", "bad name", "$(id)"):
            with self.assertRaises(ValueError):
                bridge.build_ssh_argv("vps", session)

    def test_environment_forwarding_is_removed_and_setenv_fails_closed(self):
        cleaned = bridge.sanitized_ssh_environment(
            "sendenv LANG\nsendenv LC_*\n",
            {
                "PATH": "/usr/bin",
                "LANG": "en_US.UTF-8",
                "LC_SECRET": "private",
                "CMUX_SOCKET_CAPABILITY": "private",
            },
        )
        self.assertEqual(cleaned, {"PATH": "/usr/bin"})
        with self.assertRaises(ValueError):
            bridge.sanitized_ssh_environment(
                "setenv EXAMPLE=value\n",
                {"PATH": "/usr/bin"},
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
