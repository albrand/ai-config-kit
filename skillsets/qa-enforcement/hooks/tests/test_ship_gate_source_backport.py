"""Regression checks for the sourced QA ship gate."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(os.environ.get("SHIP_GATE_SCRIPT", Path(__file__).resolve().parents[2] / "shared/qa-sweep/scripts/ship-gate.py"))
spec = importlib.util.spec_from_file_location("ship_gate", SCRIPT)
ship_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ship_gate)


class ShipGateBackportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Test"], check=True)

    def commit(self, name, contents):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", name], check=True)
        return subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()

    def test_tree_equivalent_commit_results_and_bad_sha(self):
        first = self.commit("file", "one")
        equivalent = self.commit(".qa/data", "ignored metadata")
        different = self.commit("file", "two")
        self.assertEqual(ship_gate.tree_equivalent_commits(str(self.repo), first, [equivalent, different]), [True, False])
        self.assertEqual(ship_gate.tree_equivalent_commits(str(self.repo), first, ["not-a-sha"]), [False])

    def test_lookup_budget_remains_3_2_seconds(self):
        self.assertEqual(ship_gate.LOOKUP_BUDGET_S, 3.2)

    def test_selftest_proves_slow_lookup_denied_at_3_2_seconds(self):
        env = os.environ.copy()
        env["HOME"] = str(self.repo)
        proc = subprocess.run(["python3", str(SCRIPT), "selftest"], env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("times out the slow fake at 3.2 s", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
