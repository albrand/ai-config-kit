"""Coordinator-mode: negated/solo user prompts must not block direct edits."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "coordinator-mode.py"
REPO = "/repo"
README = f"{REPO}/README.md"

HERMES_SOLO = (
    "Don't orchestrate this; edit the README directly to explain the current hooks.",
    "Fix the issue with agents in the README directly; do not delegate.",
)
COORDINATOR = (
    "orchestrate this and spawn children",
    "please coordinate children for this",
)
WRITE = {
    "tool_name": "write",
    "tool_input": {"file_path": README},
    "cwd": REPO,
}


class CoordinatorModeNegationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = self.temp.name
        self.session = "coord-negation-test"

    def run_hook(self, kind, payload):
        body = {**payload, "session_id": self.session}
        result = subprocess.run(
            [sys.executable, str(HOOK), kind],
            input=json.dumps(body),
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": self.home},
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def state_mode(self):
        path = Path(self.home) / ".agent-hooks/state/coordinator" / f"{self.session}.json"
        if not path.exists():
            return ""
        return json.loads(path.read_text()).get("mode", "")

    def prompt_then_write(self, prompt):
        self.run_hook("prompt", {"prompt": prompt})
        return self.run_hook("pretool", WRITE)

    def test_hermes_solo_prompts_allow_readme_write(self):
        for prompt in HERMES_SOLO:
            with self.subTest(prompt=prompt[:48]):
                out = self.prompt_then_write(prompt)
                self.assertFalse(out.get("block"), out)
                self.assertNotEqual(self.state_mode(), "coordinator")

    def test_coordinator_prompts_block_readme_write(self):
        for prompt in COORDINATOR:
            with self.subTest(prompt=prompt):
                out = self.prompt_then_write(prompt)
                self.assertTrue(out.get("block"), out)
                self.assertEqual(self.state_mode(), "coordinator")


if __name__ == "__main__":
    unittest.main()
