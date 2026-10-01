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
UPTAKE = ROOT.parent / "shared/scope-ledger/scripts/request-contract-uptake.py"
THREAD = "thr_test123"
SECRET_TEXT = "verbatim outcome text must never leak into telemetry"


class RequestContractLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.contract_path = self.base / "contract.json"
        self.fallback = self.base / "fallback"
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

    def env(self):
        return dict(os.environ, HOME=str(self.home), REQUEST_CONTRACT_FALLBACK_DIR=str(self.fallback))

    def block_fallback(self):
        # A regular file where the fallback directory should be: the fallback cannot be used either.
        self.fallback.write_text("not a directory", encoding="utf-8")

    def run_logger(self):
        env = self.env()
        return subprocess.run(["python3", str(LOGGER), str(self.contract_path), "--thread-id", THREAD],
                              capture_output=True, text=True, env=env)

    def run_logger_with_timeout(self):
        env = self.env()
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
        self.block_fallback()
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
        self.block_fallback()
        result = self.run_logger()
        self.assertEqual(result.returncode, 1)
        self.assertIn("could not append metadata event", result.stderr)
        self.assertNotIn(SECRET_TEXT, result.stderr)

    def test_sandbox_blocked_home_state_falls_back_to_a_private_tmp_dir(self):
        # Codex workspace-write cannot write ~/.local/state; a complying agent's event was lost (2026-10-01 probe).
        self.write_contract()
        state = self.home / ".local"
        state.mkdir()
        state.chmod(0o500)
        try:
            result = self.run_logger()
        finally:
            state.chmod(0o700)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sandbox fallback", result.stdout)
        events = self.fallback / "events.jsonl"
        event = json.loads(events.read_text(encoding="utf-8"))
        self.assertEqual(event["event"], "request-contract")
        self.assertEqual(event["row_count"], 2)
        self.assert_no_contract_text(events.read_text(encoding="utf-8"))
        self.assertEqual(self.fallback.stat().st_mode & 0o777, 0o700)
        self.assertEqual(events.stat().st_mode & 0o777, 0o600)

    def assert_no_contract_text(self, logged):
        """No string from anywhere in the contract body may reach telemetry."""
        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for item in value.values():
                    yield from strings(item)
            elif isinstance(value, list):
                for item in value:
                    yield from strings(item)
        leaked = [text for text in strings(self.contract) if len(text) > 8 and text in logged]
        self.assertEqual(leaked, [])

    def test_uptake_counts_both_files_and_separates_the_author_tree(self):
        import sqlite3
        db_path = self.base / "bb.db"
        db = sqlite3.connect(db_path)
        db.execute("create table threads (id text, parent_thread_id text)")
        db.executemany("insert into threads values (?, ?)",
                       [("thr_root", None), ("thr_child", "thr_root"), ("thr_grand", "thr_child"), ("thr_other", None)])
        db.commit()
        db.close()
        main = self.home / ".local/state/agent-quality/events.jsonl"
        main.parent.mkdir(parents=True)
        self.fallback.mkdir(mode=0o700)
        row = lambda ts, thread: json.dumps({"schema_version": 1, "ts": ts, "event": "request-contract",
                                             "thread_id": thread, "row_count": 2,
                                             "row_status_counts": {"complete": 2, "blocked": 0}})
        main.write_text("\n".join([row("2026-10-01T10:00:00+00:00", "thr_other"),
                                    row("2026-10-01T13:00:00+00:00", "thr_other"),
                                    json.dumps({"event": "evidence-claim", "ts": "2026-10-01T13:00:01+00:00"})]) + "\n")
        (self.fallback / "events.jsonl").write_text(row("2026-10-01T13:05:00+00:00", "thr_grand") + "\n")
        result = subprocess.run(["python3", str(UPTAKE), "--since", "2026-10-01T12:00:00Z",
                                 "--exclude-tree", "thr_root", "--bb-db", str(db_path)],
                                capture_output=True, text=True, env=self.env())
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["events"], 2)
        self.assertEqual(report["threads_outside_tree"], ["thr_other"])
        self.assertEqual(report["threads_inside_tree"], ["thr_grand"])
        self.assertEqual(sorted(report["files"].values()), [1, 1])

    def test_uptake_since_is_a_time_comparison_not_a_string_one(self):
        main = self.home / ".local/state/agent-quality/events.jsonl"
        main.parent.mkdir(parents=True)
        row = lambda ts, thread, rows=2: json.dumps({"schema_version": 1, "ts": ts, "event": "request-contract",
                                                    "thread_id": thread, "row_count": rows,
                                                    "row_status_counts": {"complete": rows, "blocked": 0}})
        main.write_text("\n".join([
            row("2026-10-01T12:31:46.999+00:00", "thr_before"),
            row("2026-10-01T12:31:47+00:00", "thr_at_boundary"),
            row("2026-10-01T12:31:47.500000+00:00", "thr_subsecond"),
            row("2026-10-01T12:31:47.500000+00:00", "thr_subsecond", 3),
            row("2026-10-01T12:31:47.500000+00:00", "thr_subsecond", 3),
        ]) + "\n")
        result = subprocess.run(["python3", str(UPTAKE), "--since", "2026-10-01T12:31:47Z"],
                                capture_output=True, text=True, env=self.env())
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        # at-boundary + two distinct same-second rows; the exact duplicate row counts once; the earlier row not at all
        self.assertEqual(report["events"], 3)
        self.assertEqual(report["threads_outside_tree"], ["thr_at_boundary", "thr_subsecond"])

    def test_uptake_keeps_same_second_rows_that_differ_only_in_status_counts(self):
        # Same ts, thread_id and row_count; only row_status_counts differ: two real closeouts, not a duplicate.
        main = self.home / ".local/state/agent-quality/events.jsonl"
        main.parent.mkdir(parents=True)
        base = {"schema_version": 1, "ts": "2026-10-01T13:00:00+00:00", "event": "request-contract",
                "thread_id": "thr_same", "row_count": 2}
        main.write_text("\n".join([
            json.dumps(dict(base, row_status_counts={"complete": 2, "blocked": 0})),
            json.dumps(dict(base, row_status_counts={"complete": 1, "blocked": 1})),
        ]) + "\n")
        result = subprocess.run(["python3", str(UPTAKE), "--since", "2026-10-01T12:00:00Z"],
                                capture_output=True, text=True, env=self.env())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["events"], 2)

    def test_uptake_reports_a_missing_thread_store(self):
        result = subprocess.run(["python3", str(UPTAKE), "--since", "2026-10-01T12:00:00Z",
                                 "--exclude-tree", "thr_root", "--bb-db", str(self.base / "absent.db")],
                                capture_output=True, text=True, env=self.env())
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot read bb's thread store", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_shared_or_linked_fallback_dir_is_refused(self):
        self.write_contract()
        state = self.home / ".local"
        state.mkdir()
        state.chmod(0o500)
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir(mode=0o700)
        try:
            self.fallback.mkdir(mode=0o777)
            self.fallback.chmod(0o777)
            shared = self.run_logger()
            self.fallback.rmdir()
            self.fallback.symlink_to(elsewhere)
            linked = self.run_logger()
        finally:
            state.chmod(0o700)
        for result in (shared, linked):
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("could not append metadata event", result.stderr)
        self.assertEqual(list(elsewhere.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
