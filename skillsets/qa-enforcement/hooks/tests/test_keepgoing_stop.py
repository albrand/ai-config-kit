#!/usr/bin/env python3
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import unittest


HOOKS = pathlib.Path(__file__).resolve().parents[1]
SHARED = HOOKS.parent / "shared"
NEEDS_OWNER = "Blocked on the release.\n\nNEEDS-OWNER: approve the force-push to main"

HOOK_WALL_DEADLINE = 15.0
_SPIKE_CEILING = 5.0
_OVERHEAD_SLOPE = 0.55
_OVERHEAD_INTERCEPT = 0.16
_OVERHEAD_CAP = 0.35
_TIMING_SAMPLES = 3


def _within_budget(hook_samples, baseline_samples):
    if any(hook >= _SPIKE_CEILING for hook in hook_samples):
        return False
    hook = min(hook_samples)
    baseline = min(baseline_samples)
    if hook >= HOOK_WALL_DEADLINE:
        return False
    overhead = hook - baseline
    limit = min(baseline * _OVERHEAD_SLOPE + _OVERHEAD_INTERCEPT, _OVERHEAD_CAP)
    return overhead < limit




class KeepGoingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.home = pathlib.Path(cls.tmp.name)
        (cls.home / ".agent-hooks").mkdir()
        for name in ("qa-stop-hook.sh", "keepgoing-stop.py"):
            shutil.copy(HOOKS / name, cls.home / ".agent-hooks" / name)
        for skill in ("qa-sweep", "scope-ledger"):
            shutil.copytree(SHARED / skill, cls.home / ".agents" / "skills" / skill)
        cls.env = dict(os.environ, HOME=str(cls.home))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def stop(self, stdin, script="qa-stop-hook.sh"):
        started = time.monotonic()
        runner = "python3" if script.endswith(".py") else "/bin/sh"
        proc = subprocess.run([runner, str(self.home / ".agent-hooks" / script)], input=stdin, text=True,
                              capture_output=True, env=self.env, cwd=self.tmp.name)
        self.elapsed = time.monotonic() - started
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def claude(self, text, active=False, session="s1"):
        return json.dumps({"session_id": session, "hook_event_name": "Stop", "stop_hook_active": active,
                           "last_assistant_message": text, "cwd": self.tmp.name})

    def codex(self, text, active=False, session="c1"):
        path = pathlib.Path(self.tmp.name) / f"rollout-{session}.jsonl"
        entry = {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                       "content": [{"type": "output_text", "text": text}]}}
        path.write_text(json.dumps(entry) + "\n")
        return json.dumps({"session_id": session, "turn_id": "t1", "model": "gpt", "hook_event_name": "Stop",
                           "stop_hook_active": active, "transcript_path": str(path), "cwd": self.tmp.name})

    def assertNudged(self, result):
        self.assertEqual(result.get("decision"), "block", result)
        self.assertIn("NEEDS-OWNER:", result["reason"])
        self.assertIn("[keep-going]", result["reason"])

    def assertAllowed(self, result):
        self.assertNotEqual(result.get("decision"), "block", result)

    def test_promise_is_nudged_once(self):
        text = "Tests are written.\n\nI'll run the tests next."
        for build in (self.claude, self.codex):
            self.assertNudged(self.stop(build(text)))
            self.assertAllowed(self.stop(build(text, active=True)))

    def test_conditional_wait_is_allowed_but_unconditional_promise_is_not(self):
        wait = "The child is still running.\n\nI'll report when it finishes; the watcher will notify me."
        for build in (self.claude, self.codex):
            self.assertAllowed(self.stop(build(wait)))
            self.assertNudged(self.stop(build("The child is still running.\n\nI'll run the tests next.")))

    def test_generalized_waits_are_allowed_and_plain_promises_are_not(self):
        allowed = (
            "I'm watching both cards. When the map arrives I'll check it, then plan the actual trim from it.",
            "Once CI comes back green I'll merge it.",
            "Waiting on the child, and when it finishes I'll verify its diff.",
            # Root (2026-10-28) was nudged on these: a sibling thread sending, posting or delivering is outside.
            "I'll report the walk verdicts when P6 sends them.",
            "Once the child posts its diff I'll review it.",
            "When the coordinator delivers the map I'll plan from it.",
        )
        nudged = ("I'll run the tests next.", "Next I'll update the README.",
                  # nouns that share a stem with the new event verbs are not events
                  "Once the deliverables are clear, I'll update the README.",
                  "After the postmortem draft, I'll update the README.",
                  "I'll update the README; P6 sends status often.",
                  # our own later action after "after ..." is not an outside event, old words or new
                  "After reviewing the diff, I will post the review.",
                  "After reviewing the diff, I will send the report.",
                  "After reviewing the diff I'll report back.")
        for build in (self.claude, self.codex):
            for text in allowed:
                self.assertAllowed(self.stop(build("Status noted.\n\n" + text)))
            for text in nudged:
                self.assertNudged(self.stop(build("Status noted.\n\n" + text)))

    def test_wait_excuses_only_its_own_sentence(self):
        nudged = (
            "Once the CI result arrives, I'll inspect it. I'll also rerun the tests now.",
            "The child is still running, but I'll run the tests now.",
            "Waiting on CI; meanwhile I'll update the README.",
            "While the watcher runs I'll fix the parser right away.",
            "The child is still running and I'll run the tests now.",
            "The child is still running and I'll update the README.",
            "I'll update the README after reviewing the code.",
            "When I have a moment I'll fix the parser.",
            # A semicolon separates two statements; the wait in one cannot excuse the other.
            "Waiting on CI; I'll update the README.",
            "Waiting on the child; I'll verify its diff.",
            "When CI finishes, I will inspect the result, then I will run the tests.",
            "Once the child reports I'll read it and then we'll update the README.",
            "I will run the tests when I finish reviewing the code.",
            # A state wait does not govern a comma-joined promise; a when/once conditional does.
            "Waiting on CI, I'll update the README.",
            "The child is still running, I'll fix the parser.",
            # A conditional excuses only what follows it, not a promise made before it.
            "I'll update the README, and when CI passes I'll report.",
            "I'll fix the parser, then once the child finishes I'll merge.",
            "Once we're done with the refactor I'll update the docs.",
        )
        allowed = ("When the child finishes, I'll verify its diff.",
                   "Once CI is green and the review is clean, I'll merge it.")
        for build in (self.claude, self.codex):
            for text in nudged:
                self.assertNudged(self.stop(build("Status noted.\n\n" + text), "keepgoing-stop.py"))
            for text in allowed:
                self.assertAllowed(self.stop(build("Status noted.\n\n" + text), "keepgoing-stop.py"))

    def test_immediate_promise_earlier_is_not_hidden_by_a_closing_paragraph(self):
        for text in ("Parser changed.\n\nI'll run the tests next.\n\nDone.", "Parser changed.\n\nI will run tests.\n\nDone."):
            for build in (self.claude, self.codex):
                self.assertNudged(self.stop(build(text)))
        for build in (self.claude, self.codex):
            self.assertAllowed(self.stop(build("Earlier I said I would refactor it; that landed.\n\nDone."),
                                         "keepgoing-stop.py"))

    def test_unrun_tests_closeout_is_blocked_by_the_stop_chain(self):
        for build in (self.claude, self.codex):
            for text in ("Changed the parser; tests remain unrun.", "Changed the parser.\n\nTests remain unrun.",
                         "Changed the parser.\n\nTests remain unrun because I haven't run them.",
                         "Changed the parser.\n\nTests have not been run yet.",
                         "Changed the parser.\n\nTests need to be run.",
                         "Changed the parser.\n\nThe suite hasn't been run."):
                result = self.stop(build(text))
                self.assertEqual(result.get("decision"), "block", result)
                self.assertNudged(self.stop(build(text), "keepgoing-stop.py"))
            for text in ("Changed the parser; the parser suite ran: 41 passed, 0 failed.",
                         "Changed the parser.\n\nThe walk is NOT RUN: blocked because hsrpc is on owner hold.",
                         "Changed the parser.\n\nHermes is NOT RUN yet: still running on the review host."):
                self.assertAllowed(self.stop(build(text), "keepgoing-stop.py"))

    def test_permission_question_is_nudged(self):
        text = "The branch is pushed.\n\nWant me to open the PR?"
        for build in (self.claude, self.codex):
            self.assertNudged(self.stop(build(text)))

    def test_needs_owner_line_is_allowed(self):
        for build in (self.claude, self.codex):
            self.assertAllowed(self.stop(build(NEEDS_OWNER)))
            self.assertAllowed(self.stop(build("Waiting.\n\nSTATUS: needs-owner\nNEEDS-OWNER: approve the force-push")))
            # A bare status with no stated ask is not an owner-only request.
            self.assertNudged(self.stop(build("Checked it.\n\nSTATUS: needs-owner"), "keepgoing-stop.py"))
            self.assertNudged(self.stop(build("Checked it.\n\nNEEDS-OWNER:"), "keepgoing-stop.py"))

    def test_non_owner_only_needs_owner_asks_are_nudged(self):
        asks = (
            "NEEDS-OWNER: please check the org Actions policy and billing, and restore it",
            "NEEDS-OWNER: look into why the build fails",
            "NEEDS-OWNER: review the code",
            "NEEDS-OWNER: install the package",
        )
        for build in (self.claude, self.codex):
            for ask in asks:
                result = self.stop(build("Waiting on GitHub.\n\n" + ask), "keepgoing-stop.py")
                self.assertEqual(result.get("decision"), "block", result)
                self.assertIn("This NEEDS-OWNER: ask is work you can do", result["reason"])

    def test_owner_only_needs_owner_asks_remain_allowed(self):
        asks = (
            "NEEDS-OWNER: approve the force-push to main",
            "NEEDS-OWNER: sign in to GitHub in the Chrome window I opened",
            "NEEDS-OWNER: the 6-digit code sent to your phone",
            "NEEDS-OWNER: approve the bb install (swap) for i38",
        )
        for build in (self.claude, self.codex):
            for ask in asks:
                self.assertAllowed(self.stop(build("Waiting.\n\n" + ask), "keepgoing-stop.py"))

    def test_named_watched_wait_without_needs_owner_is_allowed(self):
        text = "Both PRs wait on CI; the watcher reports when it lands."
        for build in (self.claude, self.codex):
            self.assertAllowed(self.stop(build(text), "keepgoing-stop.py"))

    def test_needs_owner_menu_is_nudged_once(self):
        menus = (
            "Stopped before building.\n\nNEEDS-OWNER: Alexandre to choose how the backend reaches staging:\n"
            "- (a) Approve a CI change to the backend deploy.\n- (b) Ship backend main as it is.\n"
            "- (c) Wait until QA approves those 4 tickets.",
            "Two routes exist.\n\nNEEDS-OWNER: option A rebases, option B cherry-picks. Which do you prefer?",
            "Done with the audit.\n\nSTATUS: needs-owner\nNEEDS-OWNER: pick between the staging and release branch.",
        )
        for build in (self.claude, self.codex):
            for text in menus:
                result = self.stop(build(text))
                self.assertNudged(result)
                self.assertIn("already asked for", result["reason"])
                self.assertAllowed(self.stop(build(text, active=True), "keepgoing-stop.py"))

    def test_needs_owner_earlier_does_not_hide_a_later_promise(self):
        text = "NEEDS-OWNER: approve the force-push to main\n\nMeanwhile I'll run the tests next."
        for build in (self.claude, self.codex):
            self.assertNudged(self.stop(build(text), "keepgoing-stop.py"))

    def test_owner_label_mention_does_not_hide_a_promise(self):
        texts = (
            "Status.\n\nNEEDS-OWNER: is only a policy label; I will run the tests next.",
            "Status.\n\nNEEDS-OWNER: approve the force-push to main\nI'll run the tests next.",
            "Status.\n\nThe NEEDS-OWNER: line is a label. I'll run the tests next.",
        )
        for build in (self.claude, self.codex):
            for text in texts:
                self.assertNudged(self.stop(build(text), "keepgoing-stop.py"))

    def test_quoted_promise_example_is_allowed(self):
        text = 'Fixed it.\n\nThe case ("I will run tests." then "Done.") failed before the fix and passes now.'
        for build in (self.claude, self.codex):
            self.assertAllowed(self.stop(build(text), "keepgoing-stop.py"))
            self.assertAllowed(self.stop(build(text.replace('"', "“", 1).replace('"', "”", 1)),
                                         "keepgoing-stop.py"))

    def test_genuine_owner_decision_is_never_told_to_self_select(self):
        menu = ("Retention is a policy call.\n\nNEEDS-OWNER: choose the retention policy:\n"
                "- (a) 30 days\n- (b) 90 days")
        single = ("Retention is a policy call.\n\nNEEDS-OWNER: approve 90-day retention for audit logs? "
                  "I recommend 90 days, because the SOC 2 audit window is 90 days.")
        for build in (self.claude, self.codex):
            reason = self.stop(build(menu), "keepgoing-stop.py")["reason"]
            # A menu is still sent back, but a choice that is truly the owner's becomes one recommended question.
            self.assertIn("one question with your recommendation", reason)
            self.assertIn("policy", reason)
            self.assertAllowed(self.stop(build(single), "keepgoing-stop.py"))

    def test_report_describing_the_menu_rule_is_allowed(self):
        text = ("The hook's suggested line and the `STATUS: needs-owner` return were the source.\n\n"
                "A NEEDS-OWNER that offers options such as (a)/(b) or says choose or pick is now sent back.")
        for build in (self.claude, self.codex):
            self.assertAllowed(self.stop(build(text), "keepgoing-stop.py"))

    def test_completed_report_is_allowed(self):
        text = "Changed the parser and added two tests.\n\n- Suite: 41 passed, 0 failed\n- Exit code: 0"
        for build in (self.claude, self.codex):
            self.assertAllowed(self.stop(build(text)))

    def test_blocked_without_owner_input_is_nudged(self):
        text = "Checked the logs.\n\nI am blocked on the failing build."
        for build in (self.claude, self.codex):
            self.assertNudged(self.stop(build(text)))

    def test_malformed_input_fails_open(self):
        for stdin in ("", "not json", "[1, 2]", "{\"last_assistant_message\": 5}", "{\"transcript_path\": \"/nonexistent\"}"):
            self.assertAllowed(self.stop(stdin, "keepgoing-stop.py"))
            self.assertAllowed(self.stop(stdin))

    def _subprocess_wall(self, argv, stdin=None):
        started = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                input=stdin,
                text=True,
                capture_output=True,
                env=self.env,
                cwd=self.tmp.name,
                timeout=HOOK_WALL_DEADLINE,
            )
        except subprocess.TimeoutExpired:
            self.fail(f"subprocess exceeded {HOOK_WALL_DEADLINE}s wall deadline: {argv!r}")
        elapsed = time.monotonic() - started
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return elapsed

    def _wall_samples(self, argv, stdin=None, samples=_TIMING_SAMPLES):
        return [self._subprocess_wall(argv, stdin=stdin) for _ in range(samples)]

    def test_run_is_fast(self):
        stdin = self.claude("Done.\n\nI'll run the tests next.")
        baseline_samples = self._wall_samples(["python3", "-c", "pass"])
        hook_samples = self._wall_samples(
            ["python3", str(self.home / ".agent-hooks" / "keepgoing-stop.py")], stdin=stdin)
        self.assertTrue(
            _within_budget(hook_samples, baseline_samples),
            f"hooks={hook_samples} baselines={baseline_samples} "
            f"deadline={HOOK_WALL_DEADLINE}s spike={_SPIKE_CEILING}s cap={_OVERHEAD_CAP}s",
        )


class WithinBudgetTests(unittest.TestCase):
    def test_must_fail_cases(self):
        cases = (
            ([0.10, 14.90, 0.10], [0.03, 0.03, 0.03]),
            ([0.10, 5.2, 0.10], [0.03, 0.03, 0.03]),
            ([1.5, 1.5, 1.5], [1.0, 1.0, 1.0]),
            ([0.53, 0.53, 0.53], [0.03, 0.03, 0.03]),
            ([17.0, 17.0, 17.0], [11.0, 11.0, 11.0]),
        )
        for hook_samples, baseline_samples in cases:
            with self.subTest(hook_samples=hook_samples, baseline_samples=baseline_samples):
                self.assertFalse(_within_budget(hook_samples, baseline_samples))

    def test_must_pass_cases(self):
        cases = (
            ([0.20, 0.60, 0.21], [0.03, 0.05, 0.03]),
            ([1.30, 1.30, 1.30], [1.0, 1.0, 1.0]),
        )
        for hook_samples, baseline_samples in cases:
            with self.subTest(hook_samples=hook_samples, baseline_samples=baseline_samples):
                self.assertTrue(_within_budget(hook_samples, baseline_samples))


if __name__ == "__main__":
    unittest.main()
