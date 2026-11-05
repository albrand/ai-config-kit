"""Coordinator-mode: negated/solo user prompts must not block direct edits."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT.parents[2]
HOOK = ROOT / "coordinator-mode.py"
REPO = "/repo"
README = f"{REPO}/README.md"

CLASSIFY_ROWS = (
    ("Don't orchestrate this; edit the README directly to explain the current hooks.", False),
    ("Fix the issue with agents in the README directly; do not delegate.", False),
    ("orchestrate this and spawn children", True),
    ("please coordinate children for this", True),
    ("orchestrate this; don't spawn more than 3 children", True),
    ("be the coordinator; do not delegate the security review, keep it on Claude", True),
    ("spawn children for the frontend; no need to delegate the migration", True),
    ("use subagents for research, but skip the children for the final review", True),
)
NON_COORDINATOR = (
    ("the orchestrate plugin needs docs", False),
    ("update the orchestrate skill readme", False),
)
CLAUSE_COORDINATOR = (
    ("don't spawn anything yet and orchestrate the rollout after lunch", True),
    ("do not delegate yet but be the coordinator for the migration", True),
    ("Do not delegate the review while you act as the coordinator for the migration", True),
    ("don't spawn more than 2 children although you should orchestrate the rollout", True),
    ("do not delegate anything until you are the orchestrator for the release", True),
)
WITH_AGENTS_COORDINATOR = (
    ("work with agents in parallel and merge directly", True),
    ("Fix the issue with agents in the README directly.", True),
)
MAIN_REGRESSION = CLASSIFY_ROWS[4:]
WRITE = {
    "tool_name": "write",
    "tool_input": {"file_path": README},
    "cwd": REPO,
}


def load_classify_from_source(source):
    spec = importlib.util.spec_from_file_location("coordinator_mode_under_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.classify


class CoordinatorModeNegationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = self.temp.name
        self.classify = load_classify_from_source(HOOK)

    def fresh_session(self):
        self.session = f"coord-neg-{next(self._session_counter)}"

    _session_counter = iter(range(1000))

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
        self.fresh_session()
        self.run_hook("prompt", {"prompt": prompt})
        return self.run_hook("pretool", WRITE)

    def test_classify_table_eight_rows(self):
        for prompt, want_coord in CLASSIFY_ROWS:
            with self.subTest(prompt=prompt[:56]):
                got = self.classify(prompt, False)
                self.assertEqual(got == "coordinator", want_coord, (got, prompt))

    def test_orchestrate_plugin_and_skill_are_not_coordinator(self):
        for prompt, want_coord in NON_COORDINATOR:
            with self.subTest(prompt=prompt):
                got = self.classify(prompt, False)
                self.assertEqual(got == "coordinator", want_coord, (got, prompt))
                self.assertEqual(got, "")

    def test_negation_does_not_swallow_later_coordinator_clause(self):
        for prompt, want_coord in CLAUSE_COORDINATOR:
            with self.subTest(prompt=prompt[:56]):
                got = self.classify(prompt, False)
                self.assertEqual(got == "coordinator", want_coord, (got, prompt))

    def test_with_agents_parallel_work_is_coordinator(self):
        for prompt, want_coord in WITH_AGENTS_COORDINATOR:
            with self.subTest(prompt=prompt[:56]):
                got = self.classify(prompt, False)
                self.assertEqual(got == "coordinator", want_coord, (got, prompt))
                out = self.prompt_then_write(prompt)
                self.assertTrue(out.get("block"), out)
                self.assertEqual(self.state_mode(), "coordinator")

    def test_main_regression_rows_still_classify_as_coordinator(self):
        main_src = subprocess.check_output(
            ["git", "show", "41e86403:skillsets/qa-enforcement/hooks/coordinator-mode.py"],
            cwd=KIT,
            text=True,
        )
        path = Path(self.temp.name) / "main-coordinator-mode.py"
        path.write_text(main_src)
        classify_main = load_classify_from_source(path)
        for prompt, want_coord in MAIN_REGRESSION:
            with self.subTest(prompt=prompt[:56]):
                got = classify_main(prompt, False)
                self.assertEqual(got == "coordinator", want_coord, (got, prompt))

    def test_solo_prompts_allow_readme_write(self):
        for prompt, want_coord in CLASSIFY_ROWS[:2]:
            with self.subTest(prompt=prompt[:48]):
                self.assertFalse(want_coord)
                out = self.prompt_then_write(prompt)
                self.assertFalse(out.get("block"), out)
                self.assertNotEqual(self.state_mode(), "coordinator")

    def test_coordinator_prompts_block_readme_write(self):
        for prompt, want_coord in CLASSIFY_ROWS[2:]:
            with self.subTest(prompt=prompt[:48]):
                self.assertTrue(want_coord)
                out = self.prompt_then_write(prompt)
                self.assertTrue(out.get("block"), out)
                self.assertEqual(self.state_mode(), "coordinator")


if __name__ == "__main__":
    unittest.main()
