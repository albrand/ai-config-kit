import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


LEDGER = Path(__file__).resolve().parents[1] / "skillsets/agent-runtime/shared/typed-decisions/scripts/decision-ledger.py"


class JevReviewLedgerReportTest(unittest.TestCase):
    def run_ledger(self, env, *args):
        return subprocess.run([sys.executable, str(LEDGER), *args], env=env, capture_output=True, text=True)

    def test_review_report_and_outcome_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "decisions.jsonl"
            env = {**os.environ, "DECISION_LEDGER": str(ledger)}
            common = ["record", "--source", "system-one", "--tier", "high", "--measurement", "synthetic peer comparison",
                      "--latency-ms", "100", "--tokens", "25", "--spend-usd", "0.001", "--batch", "2"]
            for suffix, answer, agreement in (("fF1_j1", "named-defect", "agreed"), ("fF2_j1", "delta", "disagreed")):
                recorded = self.run_ledger(env, *common, "--point", "hermes-finding-kind", "--answer", answer,
                                           "--agreement", agreement, "--ref", f"jev-hermes:pr-17@abc:c01 #{suffix}")
                self.assertEqual(recorded.returncode, 0, recorded.stderr)
            report = self.run_ledger(env, "review-report", "--days", "30")
            self.assertEqual(report.returncode, 0, report.stderr)
            self.assertIn("agreement rate: 1/2 (50.0%)", report.stdout)
            self.assertIn("tokens per review: 25 average", report.stdout)
            self.assertIn("USD per review: 0.001000 average", report.stdout)
            self.assertIn("latency p50/p95: 100/100 ms", report.stdout)
            resolved = self.run_ledger(env, "resolve-review", "--ref", "pr-17@abc", "--finding", "F1",
                                       "--outcome", "held", "--evidence", "synthetic finding accepted")
            self.assertEqual(resolved.returncode, 0, resolved.stderr)
            resolved = self.run_ledger(env, "resolve-review", "--ref", "pr-17@abc", "--finding", "F2",
                                       "--outcome", "overturned", "--evidence", "synthetic finding rejected")
            self.assertEqual(resolved.returncode, 0, resolved.stderr)
            events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            outcomes = [event for event in events if event["type"] == "outcome"]
            self.assertEqual(len(outcomes), 2)
            self.assertEqual([event["outcome"] for event in outcomes], ["held", "overturned"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
