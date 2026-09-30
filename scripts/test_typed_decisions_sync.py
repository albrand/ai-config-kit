#!/usr/bin/env python3
"""typed-decisions-sync.py must never write when asked for help or given an unknown option."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "typed-decisions-sync.py"
STALE = "# Home\n\n<!-- token-efficient-orchestration:end -->\n\n<!-- typed-decisions:begin -->\nold block\n<!-- typed-decisions:end -->\n"
# Every global file the script manages, relative to HOME. The kit path is HOME-relative
# (~/projects/agent-config-kit), so a sandbox HOME sandboxes the kit copy as well.
GLOBALS = (
    ".claude/CLAUDE.md",
    ".bb/AGENTS.md",
    ".codex/AGENTS.md",
    ".config/opencode/AGENTS.md",
    "projects/agent-config-kit/GLOBAL_AGENTS.md",
)


class TypedDecisionsSyncArgsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.targets = [self.home / rel for rel in GLOBALS]
        for target in self.targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(STALE, encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_sync(self, *args: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
        env = {key: value for key, value in os.environ.items() if key != "AI_CONFIG_KIT"}
        env.update({"HOME": str(self.home)}, **extra_env)
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, cwd=self.home, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120, check=False)

    def assert_untouched(self) -> None:
        for target in self.targets:
            self.assertEqual(target.read_text(encoding="utf-8"), STALE, str(target))

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
        self.assertEqual(result.stdout.count("STALE   global"), len(GLOBALS), result.stdout)
        self.assert_untouched()

    def test_daily_check_falsify_pair_is_accepted_and_writes_nothing(self) -> None:
        result = self.run_sync("--check", "--falsify")
        self.assertNotIn("unrecognized arguments", result.stderr)
        self.assertIn("live:", result.stdout, result.stderr)
        self.assert_untouched()

    def test_no_arguments_writes_every_sandboxed_global(self) -> None:
        result = self.run_sync()
        self.assertEqual(result.stdout.count("written global"), len(GLOBALS), result.stdout + result.stderr)
        self.assertIn(str(self.home / "projects/agent-config-kit/GLOBAL_AGENTS.md"), result.stdout)
        for target in self.targets:
            self.assertNotEqual(target.read_text(encoding="utf-8"), STALE, str(target))

    def test_ai_config_kit_selects_the_checked_kit(self) -> None:
        kit = self.home / "merged-main"
        kit.mkdir()
        (kit / "GLOBAL_AGENTS.md").write_text(STALE, encoding="utf-8")
        result = self.run_sync("--check", AI_CONFIG_KIT=str(kit))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(str(kit / "GLOBAL_AGENTS.md"), result.stdout)
        self.assertNotIn(str(self.home / "projects/agent-config-kit/GLOBAL_AGENTS.md"), result.stdout)
        self.assertEqual((kit / "GLOBAL_AGENTS.md").read_text(encoding="utf-8"), STALE)
        self.assert_untouched()


class KitBaselineTests(unittest.TestCase):
    def test_kit_baseline_carries_the_canonical_typed_block(self) -> None:
        # The bb home is rendered verbatim from GLOBAL_AGENTS.md; the other homes take GLOBAL_BLOCK.
        module = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        block = next(ast.literal_eval(node.value) for node in module.body if isinstance(node, ast.Assign)
                     and any(getattr(target, "id", "") == "GLOBAL_BLOCK" for target in node.targets))
        self.assertIn(block, (SCRIPT.parents[1] / "GLOBAL_AGENTS.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
