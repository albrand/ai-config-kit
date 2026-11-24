import json
import subprocess
import sys
import unittest
from pathlib import Path

HOOK = Path(__file__).with_name("precedence-marker-hook.py")


class PrecedenceMarkerHookTests(unittest.TestCase):
    def call_hook(self, command):
        event = {"tool_name": "Bash", "tool_input": {"command": command}}
        return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), text=True, capture_output=True)

    def test_only_marker_is_denied(self):
        blocked = self.call_hook("echo SECRETS-GUARD-PRECEDENCE-PROBE")
        self.assertEqual(json.loads(blocked.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        allowed = self.call_hook("ls -la")
        self.assertEqual(json.loads(allowed.stdout), {})


if __name__ == "__main__":
    unittest.main()
