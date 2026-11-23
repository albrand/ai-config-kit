#!/usr/bin/env python3
"""Regression coverage for the QA bindings push gate opt-in boundary."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
HOOK = Path(os.environ.get("QA_BINDINGS_HOOK", ROOT / "skillsets/qa-enforcement/hooks/qa-bindings-push-gate.py"))


class PushGateTests(unittest.TestCase):
    def check_push(self, config=None, scenario=None, hook=HOOK):
        with tempfile.TemporaryDirectory(prefix="qa-bindings-gate-") as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "QA test"], cwd=repo, check=True)
            if config is not None:
                path = repo / "qa/qa.config.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(config))
            if scenario is not None:
                path = repo / "qa/scenarios/index.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"scenarios": [scenario]}))
            else:
                (repo / "tracked.txt").write_text("fixture\n")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
            event = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                     "tool_input": {"command": "git push", "cwd": str(repo)}}
            return subprocess.run(["python3", str(hook)], input=json.dumps(event), text=True,
                                  capture_output=True, cwd=repo)

    def test_foreign_perci_config_is_not_opted_in(self):
        result = self.check_push({"board": "QA", "paths": {"scenarios": "qa/scenarios"}})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_declared_artifacts_without_scenarios_is_denied(self):
        result = self.check_push({"artifacts": {}})
        self.assertEqual(result.returncode, 2)
        self.assertIn("has no artifacts.scenarios", result.stderr)

    def test_ready_binding_to_missing_file_is_denied(self):
        result = self.check_push({"artifacts": {"scenarios": "qa/scenarios"}},
                                 {"id": "QAS-ABC234", "binding": {"status": "ready", "file": "tests/missing.spec.ts"}})
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_missing_config_is_allowed(self):
        result = self.check_push()
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
