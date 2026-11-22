import json
import subprocess
import sys
import unittest
from pathlib import Path

ADAPTER = Path.home() / ".agent-hooks/cursor-pretool.py"


class CursorAdapterTests(unittest.TestCase):
    def call_hook(self, payload):
        return subprocess.run(
            [sys.executable, str(ADAPTER)],
            input=payload,
            text=True,
            capture_output=True,
        )

    def test_before_shell_denies_fake_secret_shapes_and_preserves_normal_flow(self):
        denied_commands = [
            "cat /tmp/secrets-guard-test/prod.env",
            "echo $FAKE_DB_URI",
            "ssh hsrpc-wsl 'cat /tmp/secrets-guard-test-20261122/prod.env'",
        ]
        for command in denied_commands:
            result = self.call_hook(json.dumps({"command": command, "cwd": "/tmp"}))
            self.assertEqual(json.loads(result.stdout)["permission"], "deny", command)

        for command in ("ls -la", "git status --short"):
            result = self.call_hook(json.dumps({"command": command, "cwd": "/tmp"}))
            self.assertEqual(json.loads(result.stdout)["permission"], "ask", command)

    def test_invalid_input_fails_closed(self):
        result = self.call_hook("{bad")
        self.assertEqual(json.loads(result.stdout)["permission"], "deny")


if __name__ == "__main__":
    unittest.main()
