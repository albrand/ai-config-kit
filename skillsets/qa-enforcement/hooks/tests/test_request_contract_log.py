#!/usr/bin/env python3
"""Tests for the non-blocking request-contract metadata logger."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOGGER = ROOT.parent / "shared/scope-ledger/scripts/request-contract-log.py"
THREAD = "thr_test123"
SECRET_TEXT = "verbatim outcome text must never leak into telemetry"


class RequestContractLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.contract_path = self.base / "contract.json"
        self.contract = {
            "target": "private target detail",
            "outcomes": [
                {"request": SECRET_TEXT, "status": "complete", "evidence": "private evidence", "blocker": ""},
                {"request": "second outcome with private wording", "status": "blocked", "evidence": "",
                 "blocker": "private blocker detail"},
            ],
            "constraints": ["private constraint"],
            "state_claims": ["private current-state claim"],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def write_contract(self):
        self.contract_path.write_text(json.dumps(self.contract), encoding="utf-8")

    def run_logger(self):
        env = dict(os.environ, HOME=str(self.home))
        return subprocess.run(["python3", str(LOGGER), str(self.contract_path), "--thread-id", THREAD],
                              capture_output=True, text=True, env=env)

    def run_logger_with_timeout(self):
        env = dict(os.environ, HOME=str(self.home))
        return subprocess.run(["python3", str(LOGGER), str(self.contract_path), "--thread-id", THREAD],
                              capture_output=True, text=True, env=env, timeout=2)

    def test_appends_only_metadata_not_contract_text(self):
        self.write_contract()
        result = self.run_logger()
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self.home / ".local/state/agent-quality/events.jsonl"
        lines = events.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        event = json.loads(lines[0])
        self.assertEqual(set(event), {"schema_version", "ts", "event", "thread_id", "row_count",
                                      "row_status_counts"})
        self.assertEqual(event["schema_version"], 1)
        self.assertEqual(event["event"], "request-contract")
        self.assertEqual(event["thread_id"], THREAD)
        self.assertEqual(event["row_count"], 2)
        self.assertEqual(event["row_status_counts"], {"complete": 1, "blocked": 1})
        output = lines[0] + result.stdout + result.stderr
        for private_text in (SECRET_TEXT, "private target detail", "private evidence", "private blocker detail",
                             "private constraint", "private current-state claim"):
            self.assertNotIn(private_text, output)

    def test_rejects_malformed_contract_without_writing_an_event(self):
        self.contract["outcomes"][0]["status"] = "open"
        self.write_contract()
        result = self.run_logger()
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid contract", result.stderr)
        self.assertNotIn(SECRET_TEXT, result.stderr)
        self.assertFalse((self.home / ".local/state/agent-quality/events.jsonl").exists())

    def test_fifo_contract_is_rejected_without_blocking(self):
        fifo = self.base / "contract.fifo"
        os.mkfifo(fifo)
        self.contract_path = fifo
        started = time.monotonic()
        result = self.run_logger_with_timeout()
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(result.returncode, 2)
        self.assertIn("could not read a valid JSON contract", result.stderr)

    def test_fifo_event_path_is_rejected_without_blocking(self):
        self.write_contract()
        event_path = self.home / ".local/state/agent-quality/events.jsonl"
        event_path.parent.mkdir(parents=True)
        os.mkfifo(event_path)
        started = time.monotonic()
        result = self.run_logger_with_timeout()
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(result.returncode, 1)
        self.assertIn("could not append metadata event", result.stderr)

    def test_storage_error_fails_without_writing_contract_text(self):
        self.write_contract()
        event_path = self.home / ".local/state/agent-quality/events.jsonl"
        event_path.parent.mkdir(parents=True)
        event_path.mkdir()
        result = self.run_logger()
        self.assertEqual(result.returncode, 1)
        self.assertIn("could not append metadata event", result.stderr)
        self.assertNotIn(SECRET_TEXT, result.stderr)


if __name__ == "__main__":
    unittest.main()
