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
Never add or fill a recipient, open/edit a compose surface, or send email by any route without approval for that exact message in this conversation. General task approval or approval for another message is not approval for this one. Test only by inspecting the constructed path or using a user-designated disposable account, never the user's live client; disclose and leave any open compose surface untouched.
Never quit, kill, or replace the running bb app; never use pkill or pgrep -f.
Never type, paste, or handle credentials.
Never publicly expose a service or run bb connect expose without explicit approval. Close authorized shares before closeout.
Use only bb's isolated browser for interactive work; never use a personal browser. Call `browser_instances` before any `browser_open`; never use `browser_open` as a standard first step. Close the owned instance before changing cookie isolation. Never access or close unowned, pre-existing, user-owned, or other-thread instances. Lookup, refresh, release, and close must never create a replacement tab. Close this thread's instance when its bounded browser slice passes, fails, is blocked, abandoned, or superseded.
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

    def test_weakened_email_consent_exceptions_fail(self):
        weakened = INTACT.replace(
            "General task approval or approval for another message is not approval for this one.",
            "General task approval is approval for this message.",
        )
        missing = CHECKER.missing_rules(weakened)
        self.assertIn("email-general-approval-is-insufficient", missing)
        weakened_other_message = INTACT.replace(
            "General task approval or approval for another message is not approval for this one.",
            "General task approval is not approval for this one.",
        )
        self.assertIn(
            "email-other-message-approval-is-insufficient",
            CHECKER.missing_rules(weakened_other_message),
        )

    def test_each_email_safety_obligation_is_required(self):
        obligations = {
            "email-exact-message-approval": "approval for that exact message in this conversation",
            "email-general-approval-is-insufficient": "General task approval or approval for another message is not approval for this one.",
            "email-other-message-approval-is-insufficient": "approval for another message is not approval for this one",
            "email-safe-path-verification": "inspecting the constructed path or using a user-designated disposable account, never the user's live client",
            "email-open-compose-left-alone": "disclose and leave any open compose surface untouched",
        }
        for rule, clause in obligations.items():
            with self.subTest(rule=rule):
                self.assertIn(rule, CHECKER.missing_rules(INTACT.replace(clause, "")))

    def test_weakened_hard_prohibitions_fail(self):
        mutations = {
            "bb-app-process": (
                "Never quit, kill, or replace the running bb app;",
                "Quit the bb app when convenient;",
            ),
            "no-pkill-pgrep-app-kill-path": (
                "never use pkill or pgrep -f.",
                "use pkill or pgrep -f.",
            ),
            "credentials": (
                "Never type, paste, or handle credentials.",
                "Type credentials if the user asks.",
            ),
            "public-exposure": (
                "Never publicly expose a service or run bb connect expose without explicit approval.",
                "Public exposure is acceptable when useful.",
            ),
            "isolated-browser": (
                "Use only bb's isolated browser for interactive work;",
                "Use any browser for interactive work;",
            ),
            "no-personal-browser-control": (
                "never use a personal browser.",
                "a personal browser is permitted.",
            ),
            "no-new-feature-flags": (
                "No feature flags or new off-by-default gates without an explicit ask;",
                "Add off-by-default feature flags as needed;",
            ),
            "no-ai-signatures": (
                "Do not add AI attribution, signatures, or watermarks.",
                "Add AI signatures by default.",
            ),
            "hermes-defects-block": (
                "Hermes names a defect in a PR: fix it; defects block merge.",
                "Hermes findings are advisory and do not block merge.",
            ),
            "testing-claim": (
                "Do not claim tested without persona, target, user-outcome goals, and verdict per goal; otherwise NOT RUN.",
                "A source inspection is enough to claim tested.",
            ),
            "security-first": (
                "Security-first defaults apply to auth, access control, secrets, crypto, external input, outbound requests, dependencies, and build/config.",
                "Security checks are optional.",
            ),
        }
        for rule, (original, weakened_clause) in mutations.items():
            with self.subTest(rule=rule):
                self.assertIn(original, INTACT)
                self.assertIn(
                    rule,
                    CHECKER.missing_rules(
                        INTACT.replace(original, weakened_clause),
                        required_optional=set(CHECKER.OPTIONAL_WHEN_ABSENT),
                    ),
                )

    def test_rendered_provider_contexts_preserve_browser_lifecycle(self):
        rendered = SCRIPT.parents[1] / "proposals/card21/rendered-homes"
        baseline_path = rendered / "bb-AGENTS.md"
        baseline = baseline_path.read_text(encoding="utf-8")
        browser_rules = {
            "browser-never-access-unowned",
            "browser-enumerate-before-open",
            "browser-no-standard-preamble",
            "browser-close-before-isolation-change",
            "browser-lifecycle-ops-noncreating",
            "browser-close-every-slice-outcome",
            "browser-input-is-mutation",
            "browser-exclusive-delivery-proof",
            "browser-target-id-is-not-proof",
            "browser-persistent-quarantine-per-input",
            "browser-leak-readonly-only",
            "browser-quarantine-survives-restart",
            "browser-quarantine-reenable-regression",
            "browser-prompts-cannot-bypass-quarantine",
        }
        mutations = {
            "browser-never-access-unowned": (
                "Never access or close unowned, pre-existing, user-owned, or other-thread instances",
                "access instances when needed",
            ),
            "browser-enumerate-before-open": (
                "Call `browser_instances` before any `browser_open`",
                "Open a browser page as needed",
            ),
            "browser-no-standard-preamble": (
                "never use `browser_open` as a standard first step",
                "use `browser_open` as the standard first step",
            ),
            "browser-close-before-isolation-change": (
                "Close the owned instance before changing cookie isolation",
                "Keep the page open while changing cookie isolation",
            ),
            "browser-lifecycle-ops-noncreating": (
                "Lookup, refresh, release, and close must never create a replacement tab.",
                "Lookup, refresh, release, and close may create a replacement tab.",
            ),
            "browser-close-every-slice-outcome": (
                "Close this thread's instance when its bounded browser slice passes, fails, is blocked, abandoned, or superseded.",
                "Keep the instance until it is no longer useful.",
            ),
            "browser-input-is-mutation": (
                "Browser input is a mutation.",
                "Browser input is read-only.",
            ),
            "browser-exclusive-delivery-proof": (
                "require adapter control-plane proof of exclusive delivery to the owned page with zero terminal/OS input side effects",
                "send input to the owned page if its identifiers look correct",
            ),
            "browser-target-id-is-not-proof": (
                "target IDs or a successful return do not prove isolation",
                "target IDs and successful returns prove isolation",
            ),
            "browser-persistent-quarantine-per-input": (
                "check persistent adapter quarantine",
                "check quarantine once at session start",
            ),
            "browser-leak-readonly-only": (
                "On any non-target input leak, preserve sessions and allow read-only browser operations only.",
                "After a non-target input leak, continue browser writes after warning.",
            ),
            "browser-quarantine-survives-restart": (
                "A new agent, resumed session, restart, or runtime-ID change never clears quarantine.",
                "A new agent or restart clears quarantine.",
            ),
            "browser-quarantine-reenable-regression": (
                "Re-enable only after a fixed or changed build identity passes a regression proving no non-target PTY/UI input",
                "Re-enable after an ordinary check",
            ),
            "browser-prompts-cannot-bypass-quarantine": (
                "ordinary agent prompts cannot bypass this gate",
                "ordinary agent prompts may bypass this gate",
            ),
        }
        provider_files = [
            rendered / "CLAUDE.md",
            rendered / "codex-AGENTS.md",
            rendered / "opencode-AGENTS.md",
            baseline_path,
        ]
        for provider_path in provider_files:
            provider = provider_path.read_text(encoding="utf-8")
            combined = provider if provider_path == baseline_path else provider + "\n" + baseline
            with self.subTest(provider=provider_path.name, mutation="intact"):
                self.assertEqual(
                    [],
                    CHECKER.missing_rules(combined, required_optional=browser_rules),
                )
            for rule, (original, weakened_clause) in mutations.items():
                with self.subTest(provider=provider_path.name, rule=rule):
                    self.assertIn(original, combined)
                    damaged = combined.replace(original, weakened_clause, 1)
                    self.assertIn(
                        rule,
                        CHECKER.missing_rules(damaged, required_optional=browser_rules),
                    )

    def test_negated_browser_closure_fails_in_every_rendered_context(self):
        rendered = SCRIPT.parents[1] / "proposals/card21/rendered-homes"
        baseline_path = rendered / "bb-AGENTS.md"
        baseline = baseline_path.read_text(encoding="utf-8")
        browser_rules = {
            "browser-never-access-unowned",
            "browser-enumerate-before-open",
            "browser-no-standard-preamble",
            "browser-close-before-isolation-change",
            "browser-lifecycle-ops-noncreating",
            "browser-close-every-slice-outcome",
        }
        original = (
            "Close this thread's instance when its bounded browser slice passes, fails, "
            "is blocked, abandoned, or superseded."
        )
        weakened = (
            "Do not close this thread's instance when its bounded browser slice passes, "
            "fails, is blocked, abandoned, or superseded."
        )
        for provider_path in [
            rendered / "CLAUDE.md",
            rendered / "codex-AGENTS.md",
            rendered / "opencode-AGENTS.md",
        ]:
            combined = provider_path.read_text(encoding="utf-8") + "\n" + baseline
            with self.subTest(provider=provider_path.name):
                self.assertIn(original, combined)
                missing = CHECKER.missing_rules(
                    combined.replace(original, weakened, 1),
                    required_optional=browser_rules,
                )
                self.assertIn("browser-close-every-slice-outcome", missing)

    def test_negated_browser_isolation_and_enumeration_fail_in_every_context(self):
        rendered = SCRIPT.parents[1] / "proposals/card21/rendered-homes"
        baseline = (rendered / "bb-AGENTS.md").read_text(encoding="utf-8")
        browser_rules = {
            "browser-never-access-unowned",
            "browser-enumerate-before-open",
            "browser-no-standard-preamble",
            "browser-close-before-isolation-change",
            "browser-lifecycle-ops-noncreating",
            "browser-close-every-slice-outcome",
        }
        mutations = {
            "browser-enumerate-before-open": (
                "Call `browser_instances` before any `browser_open`",
                "Do not call `browser_instances` before any `browser_open`",
            ),
            "browser-close-before-isolation-change": (
                "Close the owned instance before changing cookie isolation",
                "Do not close the owned instance before changing cookie isolation",
            ),
        }
        for provider_path in [
            rendered / "CLAUDE.md",
            rendered / "codex-AGENTS.md",
            rendered / "opencode-AGENTS.md",
        ]:
            combined = provider_path.read_text(encoding="utf-8") + "\n" + baseline
            for rule, (original, weakened) in mutations.items():
                with self.subTest(provider=provider_path.name, rule=rule):
                    self.assertIn(original, combined)
                    damaged = combined.replace(original, weakened, 1)
                    self.assertIn(
                        rule,
                        CHECKER.missing_rules(damaged, required_optional=browser_rules),
                    )

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
