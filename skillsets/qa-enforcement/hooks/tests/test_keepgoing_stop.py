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
REAL_HOME = pathlib.Path.home()
NEEDS_OWNER = "Blocked on the release.\n\nNEEDS-OWNER: approve the force-push to main"


class KeepGoingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.home = pathlib.Path(cls.tmp.name)
        (cls.home / ".agent-hooks").mkdir()
        for name in ("qa-stop-hook.sh", "keepgoing-stop.py"):
            shutil.copy(HOOKS / name, cls.home / ".agent-hooks" / name)
        os.symlink(REAL_HOME / ".agents", cls.home / ".agents")
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
            "Waiting on the child; I'll verify its diff.",
        )
        nudged = ("I'll run the tests next.", "Next I'll update the README.")
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
        )
        allowed = ("When the child finishes, I'll verify its diff.", "Waiting on the child; I'll verify its diff.",
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

    def test_permission_question_is_nudged(self):
        text = "The branch is pushed.\n\nWant me to open the PR?"
        for build in (self.claude, self.codex):
            self.assertNudged(self.stop(build(text)))

    def test_needs_owner_line_is_allowed(self):
        for build in (self.claude, self.codex):
            self.assertAllowed(self.stop(build(NEEDS_OWNER)))
            self.assertAllowed(self.stop(build("Waiting.\n\nSTATUS: needs-owner")))

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

    def test_run_is_fast(self):
        self.stop(self.claude("Done.\n\nI'll run the tests next."), "keepgoing-stop.py")
        self.assertLess(self.elapsed, 0.2, self.elapsed)


if __name__ == "__main__":
    unittest.main()
