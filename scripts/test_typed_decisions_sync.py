#!/usr/bin/env python3
"""typed-decisions-sync.py must never write when asked for help or given an unknown option."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "typed-decisions-sync.py"
STALE = "# Home\n\n<!-- token-efficient-orchestration:end -->\n\n<!-- typed-decisions:begin -->\nold block\n<!-- typed-decisions:end -->\n"


class TypedDecisionsSyncArgsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        # One global file with a stale block: a write-mode run would rewrite it.
        self.target = self.home / ".bb" / "AGENTS.md"
        self.target.parent.mkdir(parents=True)
        self.target.write_text(STALE, encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_sync(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "HOME": str(self.home)}
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60, check=False)

    def assert_untouched(self) -> None:
        self.assertEqual(self.target.read_text(encoding="utf-8"), STALE)

    def test_help_prints_usage_and_writes_nothing(self) -> None:
        result = self.run_sync("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)
        self.assertNotIn("written global", result.stdout)
        self.assert_untouched()

    def test_unknown_option_fails_and_writes_nothing(self) -> None:
        result = self.run_sync("--dry-run")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)
        self.assert_untouched()

    def test_check_reports_without_writing(self) -> None:
        result = self.run_sync("--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("STALE", result.stdout)
        self.assert_untouched()

    def test_no_arguments_still_writes(self) -> None:
        result = self.run_sync()
        self.assertIn("written global", result.stdout, result.stderr)
        self.assertNotEqual(self.target.read_text(encoding="utf-8"), STALE)


if __name__ == "__main__":
    unittest.main()
