#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "gate-runner.py"
SPEC = importlib.util.spec_from_file_location("gate_runner", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(module)


class Clock:
    def __init__(self): self.value = 1000.0
    def __call__(self): return self.value


class GateRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gate-runner-test-"))
        self.repo = self.tmp / "repo"; self.repo.mkdir()
        self.worktree = self.tmp / "worktree"; self.worktree.mkdir()
        self.artifact = self.tmp / "evidence.txt"; self.artifact.write_text("observed")
        self.clock = Clock(); self.store = module.Store(self.tmp / "state", self.clock)
        self.target = {"repo": str(self.repo), "worktree": str(self.worktree), "branch": "fix/test", "commit": "a" * 40, "gate": "lint"}

    def tearDown(self): shutil.rmtree(self.tmp, ignore_errors=True)

    def state(self, **extra): return argparse_namespace(root=str(self.store.root), **extra)

    def test_second_start_refuses_after_pass_and_failed_gate_allows_one_repair(self):
        args = self.state(action="start", **self.target)
        self.assertEqual(module.cmd_start(self.store, args), 0)
        run_id = self.store.all_states()[0]["run_id"]
        self.assertEqual(self.store.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.store.path(run_id).stat().st_mode & 0o777, 0o600)
        finish = self.state(action="finish", run_id=run_id, status="passed", **self.ev(0))
        self.assertEqual(module.cmd_finish(self.store, finish), 0)
        with self.assertRaises(module.GuardError) as error:
            module.cmd_close(self.store, self.state(action="close", run_id=run_id, outcome="failed", **self.ev(0)))
        self.assertEqual(error.exception.code, "outcome_mismatch")
        self.assertEqual(module.cmd_start(self.store, args), module.EXIT_ALREADY_PASSED)

        self.target["gate"] = "build"
        self.assertEqual(module.cmd_start(self.store, self.state(action="start", **self.target)), 0)
        failed_id = [s for s in self.store.all_states() if s["gate"]["name"] == "build"][0]["run_id"]
        failed = self.state(action="finish", run_id=failed_id, status="failed", **self.ev(1))
        self.assertEqual(module.cmd_finish(self.store, failed), 0)
        repair = self.state(action="repair", run_id=failed_id, repair_ref="fix-cluster")
        self.assertEqual(module.cmd_repair(self.store, repair), 0)
        with self.assertRaises(module.GuardError) as error:
            module.cmd_repair(self.store, repair)
        self.assertEqual(error.exception.exit_code, module.EXIT_INVALID)
        self.assertEqual(module.cmd_finish(self.store, self.state(action="finish", run_id=failed_id, status="failed", **self.ev(1))), 0)
        with self.assertRaises(module.GuardError) as error:
            module.cmd_repair(self.store, repair)
        self.assertEqual(error.exception.exit_code, module.EXIT_REPAIR_REQUIRED)

    def test_review_expires_and_close_refuses_active_work(self):
        args = self.state(action="start", **self.target); self.assertEqual(module.cmd_start(self.store, args), 0)
        run_id = self.store.all_states()[0]["run_id"]
        with self.assertRaises(module.GuardError) as error:
            module.cmd_close(self.store, self.state(action="close", run_id=run_id, outcome="failed", **self.ev(1)))
        self.assertEqual(error.exception.exit_code, module.EXIT_HELD)
        self.assertEqual(module.cmd_review_start(self.store, self.state(action="review-start", run_id=run_id, timeout_seconds=5)), 0)
        self.clock.value += 5
        self.assertEqual(module.cmd_review_check(self.store, self.state(action="review-check", run_id=run_id)), module.EXIT_TIMED_OUT)
        state = self.store.read(run_id)
        self.assertEqual(state["review"]["status"], "timed_out")
        self.assertEqual(state["gate"]["status"], "timed_out")
        self.assertEqual(module.cmd_close(self.store, self.state(action="close", run_id=run_id, outcome="timed_out", **self.ev(module.EXIT_TIMED_OUT))), 0)

    def test_review_finish_sets_terminal_gate_state_and_allows_close(self):
        args = self.state(action="start", **self.target); self.assertEqual(module.cmd_start(self.store, args), 0)
        run_id = self.store.all_states()[0]["run_id"]
        self.assertEqual(module.cmd_review_start(self.store, self.state(action="review-start", run_id=run_id, timeout_seconds=5)), 0)
        self.assertEqual(module.cmd_review_finish(self.store, self.state(action="review-finish", run_id=run_id, status="failed", **self.ev(1))), 0)
        state = self.store.read(run_id)
        self.assertEqual(state["review"]["status"], "failed")
        self.assertEqual(state["gate"]["status"], "failed")
        self.assertEqual(module.cmd_close(self.store, self.state(action="close", run_id=run_id, outcome="failed", **self.ev(1))), 0)

    def test_status_reconciles_legacy_terminal_review_before_reporting(self):
        args = self.state(action="start", **self.target); self.assertEqual(module.cmd_start(self.store, args), 0)
        run_id = self.store.all_states()[0]["run_id"]
        state = self.store.read(run_id)
        state["review"] = {"status": "failed", "finished_at": "1970-01-01T00:16:41+00:00", "evidence": self.ev(1)}
        self.store.write(state)
        self.assertEqual(module.cmd_status(self.store, self.state(action="status", run_id=run_id)), 0)
        self.assertEqual(self.store.read(run_id)["gate"]["status"], "failed")
        self.assertEqual(module.cmd_close(self.store, self.state(action="close", run_id=run_id, outcome="failed", **self.ev(1))), 0)

    def test_stale_checkpoint_is_observable_and_evidence_is_required(self):
        args = self.state(action="start", **self.target); self.assertEqual(module.cmd_start(self.store, args), 0)
        run_id = self.store.all_states()[0]["run_id"]
        self.clock.value += module.STALE_AFTER + 1
        self.assertEqual(module.cmd_status(self.store, self.state(action="status", run_id=run_id)), module.EXIT_STALE)
        bad = self.state(action="checkpoint", run_id=run_id, phase="edit", command="rg", measurement="changed", artifact=str(self.tmp / "missing"))
        with self.assertRaises(module.GuardError): module.cmd_checkpoint(self.store, bad)

    def test_cli_returns_machine_readable_refusal(self):
        command = [sys.executable, str(SCRIPT), "--root", str(self.store.root), "start",
                   "--repo", str(self.repo), "--worktree", str(self.worktree),
                   "--branch", "fix/test", "--commit", "a" * 40, "--gate", "lint"]
        first = subprocess.run(command, capture_output=True, text=True, check=False)
        second = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, module.EXIT_HELD)
        self.assertEqual(json.loads(first.stdout)["status"], "started")
        self.assertEqual(json.loads(second.stdout)["status"], "held")

    def test_adopt_records_existing_success_without_spawning_a_gate(self):
        args = self.state(action="adopt", **self.target, **self.ev(0))
        self.assertEqual(module.cmd_adopt(self.store, args), 0)
        self.assertEqual(module.cmd_start(self.store, self.state(action="start", **self.target)), module.EXIT_ALREADY_PASSED)
        state = self.store.all_states()[0]
        self.assertTrue(state["gate"]["adopted"])

    def ev(self, exit_code): return {"command": "./scripts/lint", "measurement": "exit=%s" % exit_code, "artifact": str(self.artifact), "exit_code": exit_code}


def argparse_namespace(**kwargs):
    from argparse import Namespace
    return Namespace(**kwargs)


if __name__ == "__main__": unittest.main(verbosity=2)
