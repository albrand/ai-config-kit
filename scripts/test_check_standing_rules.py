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
Remove only clean worktrees you created; never remove your own live bb environment, another agent's/user's worktree, a dirty tree, a .keep-worktree tree, or an unreferenced detached commit. A detached review worktree must end with its command. Use git worktree remove without --force.
Do not add AI attribution, signatures, or watermarks.
Hermes names a defect in a PR: fix it; defects block merge.
Do not claim tested without persona, target, user-outcome goals, and verdict per goal; otherwise NOT RUN. PASS requires the persona to complete the full workflow; otherwise FAIL.
Security-first defaults apply to auth, access control, secrets, crypto, external input, outbound requests, dependencies, and build/config.
Never garbage-collect repositories, journals, user-owned sessions, or active sessions.
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

    def test_detached_lifetime_cannot_be_historical_only(self):
        damaged = INTACT.replace(
            "A detached review worktree must end with its command.",
            "A detached review worktree once outlived its command.",
        ) + "\nHistorical note: detached worktree must end with its command.\n"
        self.assertIn("worktree-detached-lifetime", CHECKER.missing_rules(damaged))

    def test_force_prohibition_must_apply_to_worktree_removal(self):
        damaged = INTACT.replace(
            "Use git worktree remove without --force.",
            "Never rewrite history with --force.",
        )
        self.assertIn("worktree-never-force", CHECKER.missing_rules(damaged))

    def test_nonownership_protection_cannot_be_historical_only(self):
        damaged = INTACT.replace(
            "another agent's/user's worktree, ", ""
        ) + "\nHistorical note: another agent's worktree was protected.\n"
        self.assertIn("worktree-not-owned", CHECKER.missing_rules(damaged))

    def test_entire_worktree_policy_cannot_be_historical_only(self):
        start = INTACT.index("Remove only clean worktrees you created;")
        end = INTACT.index("\nDo not add AI attribution", start)
        policy = INTACT[start:end]
        damaged = INTACT[:start] + "Historical note (no longer binding): " + policy + INTACT[end:]
        missing = CHECKER.missing_rules(damaged, require_optional=True)
        self.assertTrue(any(name.startswith("worktree-") for name in missing))

    def test_historical_note_on_adjacent_line_invalidates_policy(self):
        start = INTACT.index("Remove only clean worktrees you created;")
        damaged = INTACT[:start] + "Historical note (no longer binding):\n" + INTACT[start:]
        missing = CHECKER.missing_rules(damaged, require_optional=True)
        self.assertIn("worktree-removal", missing)
        self.assertIn("worktree-dirty-protection", missing)

    def test_historical_note_separated_by_blank_line_does_not_apply(self):
        start = INTACT.index("Remove only clean worktrees you created;")
        damaged = INTACT[:start] + "Historical note (no longer binding):\n\n" + INTACT[start:]
        self.assertNotIn(
            "worktree-removal",
            CHECKER.missing_rules(damaged, require_optional=True),
        )

    def test_each_codex_context_gc_obligation_is_required(self):
        obligations = {
            "context-gc-boundary": "Context GC is mandatory at execution boundaries",
            "context-gc-resume-packet": "retain only a compact resume packet",
            "context-gc-discard-logs": "discard raw tool logs and completed-agent transcripts",
            "context-gc-fresh-opencode-sessions": "use fresh OpenCode sessions for new plan steps",
            "context-gc-audit": "run the available GC audit across storage/process state",
            "context-gc-managed-runner-self-check": "Do not depend on a managed runner unless its installed implementation passes a live self-check",
            "no-gc-user-owned-state": "Never garbage-collect repositories, journals, user-owned sessions, or active sessions.",
        }
        policy = "\n".join(obligations.values())
        for rule, clause in obligations.items():
            with self.subTest(rule=rule):
                damaged = policy.replace(clause, "Historical note: " + clause, 1)
                missing = CHECKER.missing_rules(damaged, required_optional=set(obligations))
                self.assertIn(rule, missing)

    def test_gc_prohibition_deletion_fails_in_codex_scope(self):
        damaged = INTACT.replace(
            "Never garbage-collect repositories, journals, user-owned sessions, or active sessions.",
            "Historical note: Never garbage-collect repositories, journals, user-owned sessions, or active sessions.",
        )
        self.assertIn("no-gc-user-owned-state", CHECKER.missing_rules(damaged, require_optional=True))

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
