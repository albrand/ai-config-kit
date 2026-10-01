"""Protect Stop delivery without changing unrelated hook settings."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("hook_timeouts", Path(__file__).resolve().parents[1] / "hook-timeouts.py")
timeouts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timeouts)


class StopTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.config = self.home / ".codex/hooks.json"
        self.config.parent.mkdir()
        self.before = {"preserve": "unrelated", "hooks": {
            "PreToolUse": [{"hooks": [{"command": "/hooks/coordinator-hook-pretool.sh", "timeout": 20}]}],
            "Stop": [{"hooks": [{"command": "/hooks/qa-stop-hook.sh", "timeout": 5},
                                 {"command": "/hooks/unrelated.sh", "timeout": 3}]}]}}
        self.config.write_text(json.dumps(self.before))
        self.addCleanup(patch.stopall)
        patch.object(timeouts, "HOME", str(self.home)).start()
        patch.object(timeouts, "host_timeout", return_value=15.0).start()

    def call(self, method):
        with contextlib.redirect_stdout(io.StringIO()):
            return method([str(self.config)])

    def test_stop_chain_below_delivery_budget_is_rejected(self):
        self.assertEqual(self.call(timeouts.check), 1)

    def test_apply_changes_only_stop_timeout_and_keeps_backup(self):
        self.assertEqual(self.call(timeouts.apply), 0)
        expected = copy.deepcopy(self.before)
        expected["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 15
        self.assertEqual(json.loads(self.config.read_text()), expected)
        backups = list((self.home / ".agent-hooks/backups").glob("hook-timeouts-*/codex-hooks.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text()), self.before)

    def test_missing_stop_timeout_is_added_without_other_changes(self):
        del self.before["hooks"]["Stop"][0]["hooks"][0]["timeout"]
        self.config.write_text(json.dumps(self.before))
        self.assertEqual(self.call(timeouts.apply), 0)
        expected = copy.deepcopy(self.before)
        expected["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 15
        self.assertEqual(json.loads(self.config.read_text()), expected)

    def test_homes_without_stop_registration_keep_existing_pretool_checks(self):
        del self.before["hooks"]["Stop"]
        self.config.write_text(json.dumps(self.before))
        self.assertEqual(self.call(timeouts.check), 0)


if __name__ == "__main__":
    unittest.main()
