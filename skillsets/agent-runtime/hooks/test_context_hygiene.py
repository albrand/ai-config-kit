"""Tests for context-hygiene-policy.py. Run: python3 -m unittest skillsets/agent-runtime/hooks/test_context_hygiene.py"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

POLICY = Path(__file__).with_name("context-hygiene-policy.py")


def verdict(payload, env=None):
    p = subprocess.run([sys.executable, str(POLICY)], input=json.dumps(payload), capture_output=True, text=True,
                       env={**os.environ, **(env or {})}, timeout=30)
    return json.loads(p.stdout)


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


BIG_HEREDOC = "python3 - <<'EOF'\n" + "\n".join(f"print({i}, '{'x' * 80}')" for i in range(20)) + "\nEOF"


class ContextHygiene(unittest.TestCase):
    def test_heredoc_message_is_guidance_with_a_way_forward(self):
        v = verdict(bash(BIG_HEREDOC))
        self.assertTrue(v["block"])
        self.assertIn("Not a safety rule", v["reason"])
        self.assertIn("carry on", v["reason"])
        self.assertNotIn("Bypass", v["reason"])

    def test_its_own_remedy_is_allowed(self):
        self.assertFalse(verdict(bash("cat > /tmp/x.py <<'EOF'\n" + BIG_HEREDOC.split("\n", 1)[1]))["block"])

    def test_codex_argv_form_is_checked(self):
        v = verdict({"tool_name": "shell", "tool_input": {"command": ["/bin/zsh", "-lc", BIG_HEREDOC]}})
        self.assertTrue(v["block"])

    def test_unbounded_read_message(self):
        f = Path(tempfile.mkdtemp()) / "big.txt"
        f.write_text("x" * 20_000)
        v = verdict({"tool_name": "Read", "tool_input": {"file_path": str(f)}})
        self.assertTrue(v["block"])
        self.assertIn("Not a safety rule", v["reason"])
        self.assertFalse(verdict({"tool_name": "Read", "tool_input": {"file_path": str(f), "limit": 50}})["block"])

    def test_bb_lifecycle_stays_a_safety_block_even_when_hygiene_is_off(self):
        # The fixture is only fed to the policy as data; nothing here runs it.
        quit_bb = "osascript -e 'tell application " + '"bb"' + " to quit'"
        v = verdict(bash(quit_bb), env={"CONTEXT_HYGIENE": "off"})
        self.assertTrue(v["block"])
        self.assertTrue(v["reason"].startswith("[bb-lifecycle]"))
        self.assertNotIn("Not a safety rule", v["reason"])


if __name__ == "__main__":
    unittest.main()
