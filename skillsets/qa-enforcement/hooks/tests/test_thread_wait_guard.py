#!/usr/bin/env python3
import json
import pathlib
import os
import subprocess
import sys
import unittest


HOOK = pathlib.Path(os.environ.get("THREAD_WAIT_GUARD", pathlib.Path(__file__).resolve().parents[1] / "thread-wait-guard.py"))


class ThreadWaitGuardTests(unittest.TestCase):
    def decide(self, command):
        payload = {"tool_name": "Bash", "tool_input": {"command": command}}
        result = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True, capture_output=True)
        return result.returncode, json.loads(result.stdout) if result.stdout else {}

    def test_invalid_status_in_until_loop_denied(self):
        code, result = self.decide("until bb thread wait thr_x --status running --timeout 1h; do :; done")
        self.assertEqual(code, 2)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("pending, idle, starting, active, stopping, error", result["hookSpecificOutput"]["permissionDecisionReason"])

    def test_wait_loop_without_delay_denied(self):
        code, result = self.decide("while true; do bb thread wait thr_x --status idle; done")
        self.assertEqual(code, 2)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_wait_in_until_condition_without_delay_denied(self):
        code, result = self.decide("until bb thread wait thr_x --status active --timeout 1h; do :; done")
        self.assertEqual(code, 2)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_negated_wait_in_while_condition_without_delay_denied(self):
        code, result = self.decide("while ! bb thread wait thr_x --status idle; do :; done")
        self.assertEqual(code, 2)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_poll_interval_allows_single_wait(self):
        self.assertEqual(self.decide("bb thread wait thr_x --status active --timeout 1h --poll-interval 120000")[0], 0)

    def test_sleep_allows_wait_loop(self):
        self.assertEqual(self.decide("until bb thread wait thr_x --status idle --timeout 1h; do sleep 30; done")[0], 0)

    def test_unrelated_command_allowed(self):
        self.assertEqual(self.decide("git status --short")[0], 0)

    def test_malformed_input_fails_open(self):
        result = subprocess.run([sys.executable, str(HOOK)], input="{", text=True, capture_output=True)
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
