#!/usr/bin/env python3
"""Offline unit tests for execution-ledger.py.

No network, no real home writes. Proves redaction/rejection of forbidden fields,
that no forbidden values are stored, the summary minimum-sample threshold, and
deterministic aggregates.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MODULE_PATH = (SCRIPT_DIR.parent / "codex" / "orca-workflow-automation" / "scripts"
               / "execution-ledger.py")
_spec = importlib.util.spec_from_file_location("execution_ledger", MODULE_PATH)
el = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(el)  # type: ignore


class _LedgerEnv(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("XDG_DATA_HOME")
        self.tmp = tempfile.mkdtemp(prefix="orca-ledger-test-")
        os.environ["XDG_DATA_HOME"] = str(Path(self.tmp) / "data")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = self._saved
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ledger(self):
        return el.ledger_file()


class ValidateRejectTest(_LedgerEnv):
    def test_valid_record_accepted(self):
        cleaned = el.validate_record({
            "route": "codex", "model": "gpt-x", "provider": "openai",
            "skill": "pr-review", "tool": "edit", "elapsed": 12.5,
            "validation": "pass", "retries": 0, "repair": 0,
            "outcome": "success", "scope_drift": False,
        })
        self.assertEqual(cleaned["route"], "codex")
        self.assertNotIn("recorded_at", cleaned)  # added at envelope time

    def test_unknown_field_rejected(self):
        with self.assertRaises(el.RecordError):
            el.validate_record({"route": "x", "unexpected": 1})

    def test_prompt_rejected(self):
        for key in ("prompt", "prompts", "prompt_text"):
            with self.assertRaises(el.RecordError):
                el.validate_record({"route": "x", key: "hi"})

    def test_transcript_rejected(self):
        with self.assertRaises(el.RecordError):
            el.validate_record({"route": "x", "transcript": "..."})

    def test_env_and_env_prefixed_rejected(self):
        with self.assertRaises(el.RecordError):
            el.validate_record({"route": "x", "env": {"A": "B"}})
        with self.assertRaises(el.RecordError):
            el.validate_record({"route": "x", "env_API_KEY": "s"})

    def test_repo_url_branch_sha_rejected(self):
        for key in ("repo_url", "repository_url", "repo", "url",
                    "branch", "ref", "sha", "head", "commit", "oid"):
            with self.assertRaises(el.RecordError):
                el.validate_record({"route": "x", key: "v"})

    def test_secret_token_credential_rejected(self):
        for key in ("secret", "token", "key", "password", "credential", "api_key"):
            with self.assertRaises(el.RecordError):
                el.validate_record({"route": "x", key: "v"})

    def test_diff_and_body_rejected(self):
        for key in ("diff", "patch", "body", "content"):
            with self.assertRaises(el.RecordError):
                el.validate_record({"route": "x", key: "v"})

    def test_bad_validation_value_rejected(self):
        with self.assertRaises(el.RecordError):
            el.validate_record({"route": "x", "validation": "EXCELLENT"})

    def test_bad_outcome_value_rejected(self):
        with self.assertRaises(el.RecordError):
            el.validate_record({"route": "x", "outcome": "MAGIC"})

    def test_negative_retries_rejected(self):
        with self.assertRaises(el.RecordError):
            el.validate_record({"route": "x", "retries": -1})

    def test_bool_for_int_rejected(self):
        with self.assertRaises(el.RecordError):
            el.validate_record({"route": "x", "retries": True})

    def test_categorical_values_are_bounded_and_single_token(self):
        for value in ("contains whitespace", "line\nbreak", "x" * 129, ""):
            with self.assertRaises(el.RecordError):
                el.validate_record({"route": value})

    def test_non_finite_and_boolean_numeric_values_rejected(self):
        for value in (float("nan"), float("inf"), True):
            with self.assertRaises(el.RecordError):
                el.validate_record({"elapsed": value})


class NoForbiddenValuesStoredTest(_LedgerEnv):
    def test_recorded_row_contains_no_forbidden_values(self):
        el.append_row(self.ledger(), el._envelope(
            el.validate_record({"route": "codex", "skill": "pr-review",
                                "elapsed": 5.0, "validation": "pass",
                                "outcome": "success"})))
        text = self.ledger().read_text(encoding="utf-8")
        # Even though our own field names are absent, prove no secret-shaped or
        # forbidden KEY leaks into the stored representation.
        row = json.loads(text.strip())
        for forbidden in ("prompt", "transcript", "env", "repo_url",
                          "branch", "sha", "token", "secret"):
            self.assertNotIn(forbidden, row)

    def test_ledger_file_mode_is_restrictive(self):
        el.append_row(self.ledger(), el._envelope(
            el.validate_record({"route": "x", "outcome": "success"})))
        mode = self.ledger().stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)


class SummaryThresholdTest(_LedgerEnv):
    def _seed(self, n):
        for i in range(n):
            el.append_row(self.ledger(), el._envelope(
                el.validate_record({"route": "codex", "skill": "pr-review",
                                     "elapsed": float(i + 1),
                                     "validation": "pass" if i % 2 == 0 else "fail",
                                     "outcome": "success" if i % 2 == 0 else "failure",
                                     "retries": i % 2, "repair": 0,
                                     "scope_drift": False})))

    def test_below_threshold_no_aggregates(self):
        self._seed(3)
        rows, _ = el.read_rows(self.ledger())
        payload = el.summarize(rows, min_samples=5)
        self.assertFalse(payload["sufficient"])
        self.assertIsNone(payload["aggregates"])
        self.assertEqual(payload["recommendations"], [])

    def test_at_threshold_emits_aggregates(self):
        self._seed(5)
        rows, _ = el.read_rows(self.ledger())
        payload = el.summarize(rows, min_samples=5)
        self.assertTrue(payload["sufficient"])
        self.assertIsNotNone(payload["aggregates"])
        self.assertEqual(payload["aggregates"]["count"], 5)
        self.assertIn("codex", payload["by_route"])
        self.assertIn("pr-review", payload["by_skill"])

    def test_invalid_threshold_rejected(self):
        with self.assertRaises(ValueError):
            el.summarize([], min_samples=0)


class DeterministicAggregateTest(_LedgerEnv):
    def test_median_and_rates_are_deterministic(self):
        for elapsed in (2.0, 4.0, 6.0, 8.0, 10.0):
            el.append_row(self.ledger(), el._envelope(
                el.validate_record({"route": "codex", "skill": "s",
                                     "elapsed": elapsed, "validation": "pass",
                                     "outcome": "success"})))
        rows, _ = el.read_rows(self.ledger())
        payload = el.summarize(rows, min_samples=5)
        # median of [2,4,6,8,10] == 6
        self.assertEqual(payload["aggregates"]["elapsed_median"], 6.0)
        self.assertEqual(payload["aggregates"]["success_rate"], 1.0)
        self.assertEqual(payload["aggregates"]["validated_rate"], 1.0)
        self.assertEqual(payload["aggregates"]["retries"], 0)
        self.assertEqual(payload["aggregates"]["repair"], 0)
        self.assertEqual(payload["aggregates"]["scope_drift"], 0)

    def test_recommendation_fires_on_high_repair_route(self):
        # 3 success with repair, 2 success without -> route 'bad' repair rate 0.6
        for i in range(3):
            el.append_row(self.ledger(), el._envelope(
                el.validate_record({"route": "bad", "skill": "s",
                                     "elapsed": 1.0, "validation": "pass",
                                     "outcome": "success", "repair": 1})))
        for i in range(2):
            el.append_row(self.ledger(), el._envelope(
                el.validate_record({"route": "bad", "skill": "s",
                                     "elapsed": 1.0, "validation": "pass",
                                     "outcome": "success", "repair": 0})))
        rows, _ = el.read_rows(self.ledger())
        payload = el.summarize(rows, min_samples=5)
        recs = payload["recommendations"]
        self.assertTrue(any("bad" in r and "repair" in r for r in recs))


class CliRecordSummaryTest(_LedgerEnv):
    def test_record_then_summary_cli(self):
        rc = el.main(["record", json.dumps({"route": "codex", "skill": "s",
                                             "elapsed": 3.0, "validation": "pass",
                                             "outcome": "success"})])
        self.assertEqual(rc, 0)
        # summary below threshold still works (no aggregates)
        import io
        buf = io.StringIO()
        orig = sys.stdout
        sys.stdout = buf
        try:
            rc2 = el.main(["summary", "--min-samples", "5"])
        finally:
            sys.stdout = orig
        self.assertEqual(rc2, 0)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["sufficient"])
        self.assertEqual(payload["count"], 1)

    def test_record_rejects_forbidden_via_cli(self):
        rc = el.main(["record", json.dumps({"route": "x", "prompt": "secret"})])
        self.assertEqual(rc, 2)
        # nothing written
        self.assertFalse(self.ledger().exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
