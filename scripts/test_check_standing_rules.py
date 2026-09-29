"""Focused fixtures for check-standing-rules.py."""

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("check-standing-rules.py")
SPEC = importlib.util.spec_from_file_location("check_standing_rules", SCRIPT)
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)

INTACT = """
Never add or fill a recipient, open/edit a compose surface, or send email by any route without approval for that exact message in this conversation. Test only by inspecting the constructed path or using a user-designated disposable account, never the user's live client; disclose and leave any open compose surface untouched.
Never quit, kill, or replace the running bb app; never use pkill or pgrep -f.
Never type, paste, or handle credentials.
Never publicly expose a service or run bb connect expose without explicit approval. Close authorized shares before closeout.
Use only bb's isolated browser for interactive work; never use a personal browser.
No feature flags or new off-by-default gates without an explicit ask; preserve auth, authorization, entitlements, environment configuration, and existing flags. A requested flag needs a removal ticket and default-on date.
Remove only clean worktrees you created; never remove your own live bb environment, another agent's/user's worktree, a dirty tree, a .keep-worktree tree, or an unreferenced detached commit. A detached review worktree must end with its command. Never use --force.
Do not add AI attribution, signatures, or watermarks.
Hermes names a defect in a PR: fix it; defects block merge.
Do not claim tested without persona, target, user-outcome goals, and verdict per goal; otherwise NOT RUN. PASS requires the persona to complete the full workflow; otherwise FAIL.
Security-first defaults apply to auth, access control, secrets, crypto, external input, outbound requests, dependencies, and build/config.
"""


class StandingRuleCheckerTest(unittest.TestCase):
    def test_intact_fixture_passes(self):
        self.assertEqual(CHECKER.missing_rules(INTACT), [])

    def test_deleted_rule_fails(self):
        damaged = INTACT.replace(
            "Never type, paste, or handle credentials.\n", ""
        )
        self.assertIn("credentials", CHECKER.missing_rules(damaged))

    def test_deleted_keep_worktree_protection_fails(self):
        damaged = INTACT.replace(
            "a .keep-worktree tree, or an unreferenced detached commit",
            "or an unreferenced detached commit",
        ) + "\nHistorical marker: .keep-worktree.\n"
        self.assertIn("worktree-keep-protection", CHECKER.missing_rules(damaged))

    def test_deleted_dirty_tree_protection_fails(self):
        damaged = INTACT.replace(
            "Remove only clean worktrees you created;",
            "Manage worktrees carefully;",
        ).replace("a dirty tree, a .keep-worktree tree", "a .keep-worktree tree")
        damaged += "\nHistorical note: dirty trees were encountered.\n"
        self.assertIn("worktree-dirty-protection", CHECKER.missing_rules(damaged))

    def test_deleted_detached_commit_protection_fails_with_history_retained(self):
        damaged = INTACT.replace(
            ", or an unreferenced detached commit",
            ", or an approved cleanup",
        ) + "\nHistorical note: unreferenced detached commits were recovered.\n"
        self.assertIn("worktree-unreferenced-detached", CHECKER.missing_rules(damaged))

    def test_deleted_own_environment_protection_fails_in_strict_home(self):
        damaged = INTACT.replace("never remove your own live bb environment, ", "")
        damaged += "\nHistorical note: own live bb environment was in use.\n"
        self.assertIn(
            "worktree-own-bb-environment",
            CHECKER.missing_rules(damaged, require_optional=True),
        )

    def test_deleted_rule_in_file_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "AGENTS.md"
            path.write_text(
                INTACT.replace(
                    "Never publicly expose a service or run bb connect expose without explicit approval. Close authorized shares before closeout.\n",
                    "",
                ),
                encoding="utf-8",
            )
            ok, failures = CHECKER.check_files([path])
        self.assertFalse(ok)
        self.assertIn("public-exposure", failures[0])


if __name__ == "__main__":
    unittest.main()
