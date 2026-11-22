import json
import subprocess
import sys
import unittest
from pathlib import Path

ADAPTER = Path(__file__).parents[1] / "security/secrets-guard/hermes-pretool.py"


class HermesAdapterTests(unittest.TestCase):
    def call_hook(self, payload):
        return subprocess.run(
            [sys.executable, str(ADAPTER)],
            input=payload,
            text=True,
            capture_output=True,
        )

    def test_terminal_secret_shapes_are_blocked_and_safe_commands_continue(self):
        for command in (
            "cat /tmp/secrets-guard-test/prod.env",
            "echo $FAKE_TOKEN",
            "ssh hsrpc-wsl 'cat /tmp/secrets-guard-test-20261122/prod.env'",
        ):
            result = self.call_hook(json.dumps({"tool_name": "terminal", "tool_input": {"command": command}}))
            self.assertEqual(json.loads(result.stdout)["decision"], "block", command)

        result = self.call_hook(json.dumps({"tool_name": "terminal", "tool_input": {"command": "ls -la"}}))
        self.assertEqual(json.loads(result.stdout), {})

    def test_direct_credential_file_reads_and_internal_errors_are_blocked(self):
        result = self.call_hook(json.dumps({"tool_name": "read_file", "tool_input": {"path": "/tmp/secrets-guard-test/prod.env"}}))
        self.assertEqual(json.loads(result.stdout)["decision"], "block")
        result = self.call_hook("{bad")
        self.assertEqual(json.loads(result.stdout)["decision"], "block")


if __name__ == "__main__":
    unittest.main()
