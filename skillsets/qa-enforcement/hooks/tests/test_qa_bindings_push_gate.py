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
    def check_push(self, config=None, scenario=None, hook=HOOK, scenario_file="qa/scenarios/index.json", binding_file=None):
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
                path = repo / scenario_file
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"scenarios": scenario if isinstance(scenario, list) else [scenario]}))
            if binding_file is not None:
                path = repo / binding_file
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("test('@QAS-ABC234', () => {});\n")
            else:
                (repo / "tracked.txt").write_text("fixture\n")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
            event = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                     "tool_input": {"command": "git push", "cwd": str(repo)}}
            return subprocess.run(["python3", str(hook)], input=json.dumps(event), text=True,
                                  capture_output=True, cwd=repo)

    def test_foreign_perci_config_with_unbound_scenario_is_allowed(self):
        result = self.check_push({
            "board": "QA-123", "team": "Perci", "acceptanceHeadings": ["Acceptance criteria"],
            "environments": ["test", "production"],
            "paths": {"requirements": "qa/requirements", "scenarios": "qa/scenarios",
                      "designs": "qa/designs", "runs": "qa/runs", "reports": "qa/reports",
                      "bugs": "qa/bugs", "manual": "qa/manual"},
        }, {"id": "QAS-ABC234", "title": "Example scenario"})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_paths_scenarios_folder_without_json_is_denied(self):
        config = {"paths": {"scenarios": "qa/typo"}}
        result = self.check_push(config)
        self.assertEqual(result.returncode, 2)
        self.assertIn("paths.scenarios 'qa/typo' has no scenario files", result.stderr)

    def test_paths_scenario_missing_binding_file_is_denied(self):
        config = {"paths": {"scenarios": "qa/scenarios"}}
        scenario = {"id": "QAS-ABC234", "title": "Example", "binding": {"status": "ready", "file": "tests/missing.spec.ts"}}
        result = self.check_push(config, scenario, scenario_file="qa/scenarios/one.json")
        self.assertEqual(result.returncode, 2, result.stderr)

    def test_paths_scenario_with_binding_file_is_allowed(self):
        config = {"paths": {"scenarios": "qa/scenarios"}}
        scenario = {"id": "QAS-ABC234", "title": "Example", "binding": {"status": "ready", "file": "tests/example.spec.ts"}}
        result = self.check_push(config, scenario, scenario_file="qa/scenarios/one.json", binding_file="tests/example.spec.ts")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_nested_paths_scenario_without_binding_is_allowed(self):
        result = self.check_push({"paths": {"scenarios": "qa/scenarios"}},
                                 {"id": "QAS-ABC234", "title": "Nested"},
                                 scenario_file="qa/scenarios/sub/a.json")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_nested_ready_binding_missing_file_is_denied_for_both_layouts(self):
        scenario = {"id": "QAS-ABC234", "title": "Nested",
                    "binding": {"status": "ready", "file": "tests/missing.spec.ts"}}
        for config in ({"paths": {"scenarios": "qa/scenarios"}},
                       {"artifacts": {"scenarios": "qa/scenarios"}}):
            with self.subTest(config=config):
                result = self.check_push(config, scenario, scenario_file="qa/scenarios/sub/b.json")
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_nested_json_scenario_counts_for_paths_folder(self):
        result = self.check_push({"paths": {"scenarios": "qa/scenarios"}},
                                 {"id": "QAS-ABC234", "title": "Nested"},
                                 scenario_file="qa/scenarios/sub/only.json")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_declared_artifacts_without_scenarios_is_denied(self):
        result = self.check_push({"artifacts": {}})
        self.assertEqual(result.returncode, 2)
        self.assertIn("has no artifacts.scenarios", result.stderr)

    def test_non_object_config_is_denied_clearly(self):
        result = self.check_push([])
        self.assertEqual(result.returncode, 2)
        self.assertIn("qa/qa.config.json must be a JSON object", result.stderr)

    def test_null_artifacts_is_denied(self):
        result = self.check_push({"artifacts": None})
        self.assertEqual(result.returncode, 2)
        self.assertIn("has no artifacts.scenarios", result.stderr)

    def test_config_without_artifacts_or_paths_is_denied(self):
        for config in ({}, {"board": "github"}):
            with self.subTest(config=config):
                result = self.check_push(config)
                self.assertEqual(result.returncode, 2)
                self.assertIn("has no artifacts.scenarios", result.stderr)

    def test_incomplete_paths_signature_is_denied(self):
        for paths in ({}, {"scenarios": ""}, {"scenarios": 7}, "qa"):
            with self.subTest(paths=paths):
                result = self.check_push({"paths": paths})
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
