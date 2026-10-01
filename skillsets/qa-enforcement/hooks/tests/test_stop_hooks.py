#!/usr/bin/env python3
"""Focused fixtures for final-claim Stop behavior and Codex trust scope."""
import ast
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
EVIDENCE = ROOT.parent / "shared/qa-sweep/scripts/evidence-stop.py"
SHIP = ROOT.parent / "shared/qa-sweep/scripts/ship-gate.py"
TRUST = ROOT / "codex-hook-trust.py"
STOP = ROOT / "qa-stop-hook.sh"
SPEC = importlib.util.spec_from_file_location("evidence_stop_fixture", EVIDENCE)
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)


def run(cmd, *, env=None, cwd=None, data=None):
    return subprocess.run(cmd, cwd=cwd, env=env, input=data, text=True, capture_output=True, check=True)


class StopHooksTests(unittest.TestCase):
    def test_compact_evidence_accepts_field_order_and_markdown(self):
        packet = "Done.\n**Target:** Python hook stack, commit abc1234\n**Persona:** coding agent\n**Goal:** continue and run checks\n**Verdict:** PASS — checks completed."
        self.assertFalse(evidence.inspect(packet)["block"])
        table = "Done.\n| Field | Evidence |\n| --- | --- |\n| Persona | coding agent |\n| Target | Python hook stack, SHA abc1234 |\n| User outcome | run continuation checks |\n| Verdict | PASS — checks completed |"
        self.assertFalse(evidence.inspect(table)["block"])

    def test_packets_written_by_the_live_probe_are_recognised(self):
        # thr_v4rqr4jadx (2026-10-01) wrote both of these; the hook rejected both.
        table = ("### QA evidence packet\n\n- **Persona:** Scheduler team engineer\n"
                 "- **Target:** Python unittest; `HEAD` `cb0a373fb69cd6cb46b32cf2d017621b0f4c205a`, with the "
                 "requested changes in the working tree.\n- **Command:** `python3 -m unittest discover -s tests -v`\n\n"
                 "| Goal attempted | Expected | Observed | Verdict |\n|---|---|---|---|\n"
                 "| Parse `1h30m` and `2m15s` | Return 5400 and 135 | `test_compound_units` passed | **PASS** |\n"
                 "| Document compound input in README | Example shows `1h30m` | Example is present | **PASS** |")
        listed = ("**QA evidence packet**\n\n- **Persona:** Scheduler team engineer.\n"
                  "- **Target:** Python, `HEAD cb0a373fb69cd6cb46b32cf2d017621b0f4c205a`, with requested changes.\n\n"
                  "**User outcomes and verdicts**\n\n1. **Compound parsing:** Expected `1h30m \u2192 5400`; observed "
                  "the assertion pass. **PASS**\n2. **README example updated:** observed the example. **PASS**")
        fixtures = pathlib.Path(__file__).parent / "fixtures"
        verbatim = [(fixtures / name).read_text(encoding="utf-8")
                    for name in ("live-probe-packet-table.md", "live-probe-packet-list.md")]
        for packet in (table, listed, *verbatim):
            with self.subTest(packet=packet[:40]):
                self.assertTrue(evidence.has_evidence_packet(packet))
        # Still not a packet: a table with no verdict column, an outcomes section with no verdict, no commit.
        self.assertFalse(evidence.has_evidence_packet(table.replace("| Verdict |", "| Notes |")))
        self.assertFalse(evidence.has_evidence_packet(listed.replace("**PASS**", "")))
        self.assertFalse(evidence.has_evidence_packet(table.replace("cb0a373fb69cd6cb46b32cf2d017621b0f4c205a", "latest")))
        self.assertFalse(evidence.has_evidence_packet(table.replace("**PASS**", "pass")), "lowercase table verdict")
        head = "Persona: scheduler engineer\nTarget: repo HEAD cb0a373\n"
        stale = (head + "| Goal | Verdict | Notes |\n|---|---|---|\n\nUnrelated steps:\n\n"
                 "| Step | Status | Notes |\n|---|---|---|\n| build | PASS | n/a |")
        self.assertFalse(evidence.has_evidence_packet(stale), "a later table must not reuse stale columns")
        command = ("Persona: scheduler engineer\nTarget: Python unittest\n- Command: git rev-parse HEAD gives abc1234f\n"
                   "Goal: parse durations\nVerdict: PASS")
        self.assertFalse(evidence.has_evidence_packet(command), "a Command line must not lend the target a hash")
        prose = (head + "**User outcomes and verdicts**\n1. Parse durations: observed the assertion.\n\n"
                 "Integration NOT RUN.")
        self.assertFalse(evidence.has_evidence_packet(prose), "prose after the section is not a verdict")
        leaked = (head + "Goal: parse durations\nVerdict:\n\n| Goal | Observed | Verdict |\n|---|---|---|\n"
                  "| parse | ran | the assertion pass |")
        self.assertFalse(evidence.has_evidence_packet(leaked), "an empty Verdict: label must not relax the table check")
        self.assertTrue(evidence.has_evidence_packet(head + "Goal: parse durations\nVerdict: pass"),
                        "a labelled verdict may still be lowercase")

    def test_completion_claims_with_quantified_subjects_are_detected(self):
        # Verbatim from the post-#38 live probe (thr_qui59i83c3), which closed with tests unrun and no nudge.
        probe = ("All three requested changes are complete.\n\n- Updated durations.py to parse compound units.\n"
                 "- `git diff --check` passed. Tests were **not run**. No push, messages, or spawns.")
        for text in (probe, "Both fixes are done.", "The three requested changes are complete.",
                     "All three PRs are merged.", "The fix is merged.", "After: all three changes are done.",
                     "Before handing off, all three fixes are done.", "After the sweep, the release is verified.",
                     "Before dispatch I fixed three defects in the executor prompt.",
                     "I worked in an isolated copy and touched nothing. I verified the run.",
                     "Nothing is deployed yet, but all three fixes are done.",
                     "Could you check? Everything is done.", "If it helps, all three fixes are done.",
                     "Should I wait? All three changes are complete.", "When can we talk? The fix is merged.",
                     "These changes are now complete.", "All requested items are finished.",
                     "The requested work is done."):
            with self.subTest(text=text[:40]):
                self.assertTrue(evidence.inspect(text)["block"], text)
        for text in ("Are all three changes complete?", "Not all three changes are complete yet.",
                     "Here is the plan for the three changes.", "None of the three items is fixed.",
                     "When each fix is ready, I'll queue it.", "Confirm the Vercel deployment is ready.",
                     "V is now confirming the production deployment is READY.",
                     "The new test feeds `all authorized work is complete.` to the hook.",
                     "Fixture:\n```\nAll three requested changes are complete.\n```",
                     "Recommendation: approve updating our checks so each change is tested as it will look after merging.",
                     "If the focused suite passes: all three changes are done.",
                     "Once both PRs are merged: the release is ready.",
                     "Merged `origin/develop` into the branch.", "I released the session lease.",
                     "I remove each builder's copy of the code once its work is merged.",
                     "Nothing in it is merged or deployed yet.",
                     'The reviewer flagged "All three PRs are merged." as unmatched.',
                     "Once everything is fixed, I push.", "Remaining before this is done:",
                     "When the fix is merged, I'll tell K1.", "If the suite passes, the release is ready."):
            with self.subTest(text=text):
                self.assertFalse(evidence.inspect(text)["block"], text)

    def test_empty_or_incomplete_evidence_still_blocks(self):
        base = "Done.\nPersona: coding agent\nTarget: Python stack commit abc1234\nGoals attempted: run checks\nVerdict: PASS — completed checks."
        for field, replacement in (("Persona: coding agent", "Persona:"), ("Goals attempted: run checks", "Goals attempted:"), ("Verdict: PASS — completed checks.", "Verdict:"), ("commit abc1234", "commit unknown")):
            with self.subTest(field=field):
                self.assertTrue(evidence.inspect(base.replace(field, replacement))["block"])
        quoted = "\n".join("> " + line for line in base.splitlines()[1:])
        self.assertTrue(evidence.inspect("Done.\n" + quoted)["block"])
        self.assertTrue(evidence.inspect("Done.\n```text\n" + base + "\n```")["block"])

    def test_complete_stop_hook_rejects_heading_only_fields_and_keeps_valid_formats(self):
        base = "Done.\nPersona: coding agent\nTarget: Python stack commit abc1234\nGoals attempted: run checks\nVerdict: PASS — completed checks."
        for field, heading in (("Persona: coding agent", "Persona:\n## Evidence"),
                               ("Goals attempted: run checks", "Goals attempted:\n## Results"),
                               ("Persona: coding agent", "Persona:\nEvidence\n---"),
                               ("Goals attempted: run checks", "Goals attempted:\nResults\n---"),
                               ("Persona: coding agent", "Persona:\nEvidence\n==="),
                               ("Goals attempted: run checks", "Goals attempted:\nResults\n==="),
                               ("Persona: coding agent", "Persona:\n<h2>Evidence</h2>"),
                               ("Goals attempted: run checks", "Goals attempted:\n<h2>Results</h2>")):
            with self.subTest(field=field):
                self.assert_stop_fixture("heading is not evidence", opted_in=False, transcript=False,
                                         expected="[qa-evidence]", claim=base.replace(field, heading))
        valid = [base,
                 "Done.\nPersona:\n  coding agent\nTarget:\n  Python stack commit abc1234\nGoal:\n- run checks\nVerdict:\n- PASS — completed checks.",
                 "Done.\n**Target:** Python stack commit abc1234\n**Persona:** coding agent\n**Goal:** run checks\n**Verdict:** PASS — completed checks.",
                 "Done.\n| Persona | coding agent |\n| Target | Python stack commit abc1234 |\n| Goal | run checks |\n| Verdict | PASS — completed checks |"]
        for packet in valid:
            with self.subTest(packet=packet):
                output = self.assert_stop_fixture("valid evidence", opted_in=False, transcript=False,
                                                  expected="", claim=packet)
                self.assertEqual(output.strip(), "")

    def test_transcript_fallback_reads_last_assistant_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            transcript = pathlib.Path(temp) / "transcript.jsonl"
            transcript.write_text("\n".join([
                json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "old"}]}}),
                json.dumps({"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done — the workflow is fixed."}]}}),
            ]) + "\n")
            result = run(["python3", str(EVIDENCE)], data=json.dumps({"transcript_path": str(transcript)}))
            self.assertEqual(json.loads(result.stdout)["decision"], "block")

    def test_claim_events_record_metadata_without_message_text(self):
        with tempfile.TemporaryDirectory() as temp:
            events = pathlib.Path(temp) / "events.jsonl"
            repo = pathlib.Path(temp) / "repo"
            repo.mkdir()
            run(["git", "init", "-q", "-b", "main"], cwd=repo)
            env = dict(os.environ, QA_GATE_EVENTS_FILE=str(events))
            messages = [
                {"cwd": str(repo), "runtime": "fixture-runtime", "provider": "fixture-provider",
                 "text": "Done — PRIVATE_MESSAGE_MUST_NOT_BE_LOGGED."},
                {"cwd": str(repo), "text": "Implemented; workflow NOT RUN; remaining: execute the workflow."},
                {"cwd": str(repo), "text": "Still working through the change."},
                {"cwd": str(repo), "runtime": "PRIVATE RUNTIME LABEL MUST NOT BE LOGGED",
                 "text": "Done."},
            ]
            decisions = []
            for payload in messages:
                result = run(["python3", str(EVIDENCE)], env=env, data=json.dumps(payload))
                decisions.append(json.loads(result.stdout)["decision"])
            self.assertEqual(decisions, ["block", "allow", "allow", "block"])
            rows = [json.loads(line) for line in events.read_text().splitlines()]
            self.assertEqual(len(rows), 3)
            self.assertEqual([row["decision"] for row in rows], ["block", "allow", "block"])
            self.assertEqual([row["claim"] for row in rows], ["done", "implemented", "done"])
            self.assertEqual(rows[0]["runtime"], "fixture-runtime")
            self.assertEqual(rows[0]["provider"], "fixture-provider")
            self.assertEqual(rows[0]["cwd"], str(repo.resolve()))
            self.assertEqual(rows[2]["runtime"], "")
            self.assertTrue(rows[0]["ts"])
            self.assertNotIn("PRIVATE_MESSAGE_MUST_NOT_BE_LOGGED", events.read_text())
            self.assertNotIn("PRIVATE RUNTIME LABEL MUST NOT BE LOGGED", events.read_text())

    def test_stop_hook_inventory_precedes_evidence_nudge(self):
        self.assert_stop_fixture("opted-in inventory row wins", opted_in=True, transcript=False,
                                 expected="[qa-sweep]", claim="Done — the workflow is fixed.")

    def test_stop_hook_nudges_without_repo_opt_in(self):
        self.assert_stop_fixture("default claim nudge", opted_in=False, transcript=False,
                                 expected="[qa-evidence]", claim="Done — the workflow is fixed.")

    def test_nudge_asks_to_run_before_offering_not_run(self):
        # A Codex probe answered the nudge by relabelling a sub-second test run as NOT RUN and stopping.
        result = run(["python3", str(EVIDENCE)], data=json.dumps({"last_assistant_message": "Done — all three changes."}))
        reason = json.loads(result.stdout)["reason"]
        self.assertLess(reason.index("run them first"), reason.index("workflow NOT RUN"))
        self.assertIn("Only when it cannot be run now", reason)
        self.assertIn("name the blocker", reason)

    FIRST_CLAIM = "I have implemented the fix."
    UNANSWERED = [
        # The 2026-10-01 probe's reply, then the phrasings found in review: each is neither a packet nor a
        # named outside blocker, so none of them may close the turn.
        "Completed all three requested items.\n`git diff --check` passed. Tests were **not run**.",
        "Implemented; workflow NOT RUN; remaining: run the suite.",
        "Tests were not run. The suite requires Python 3.12.", "Tests were not run in the sandbox environment.",
        "I didn't run the tests.", "Shipped without running the suite.", "No tests were run.",
        "Tests have not been run.", "The tests weren't executed.", "None of the tests ran.", "I skipped the tests.",
        "Tests were not run \u2014 I can't run them here.", "Tests were not run. Blocker: none.",
        "Tests were not run because I ran out of time, so I cannot run them: later.",
        "Tests were not run; blocked by time.", "Tests were not run; blocked by other priorities.",
        "Tests were not run; blocked by capacity.", "Tests were not run. Blocker: none of the above.",
        "Tests were not run. Blocker: nothing further.",
        "I didn't test it.", "Haven't tested yet.", "The change is untested.", "Tests remain unrun.",
        "No testing was done.", "Testing was not performed.", "I didn't get to the tests.",
        "Didn't verify it.", "Not verified.", "Verification is pending.", "I'll run the tests next.",
        "Tests: pending.", "QA pending.", "Left the tests for later.", "Will test later.", "TODO: run tests.",
        "I have not validated the workflow.", "I haven't checked it end to end.", "Not tested.",
        "Didn't run anything.", "I did not try it in the browser.", "Here is the summary you asked for.",
    ]
    ANSWERED = [
        "Done.\nPersona: coding agent\nTarget: Python stack commit abc1234\nGoals attempted: run checks\n"
        "Verdict: PASS \u2014 completed checks.",
        "Implemented; workflow NOT RUN. Blocker: the staging login requires the owner's credentials.",
        "Tests were not run: blocked by the sandbox, which has no network to install the test runner.",
        "The tests cannot be run here because the sandbox has no network; remaining: run them in CI.",
        "Tests were not run: blocked by missing owner credentials; will tidy docs later.",
        "Tests were not run. Blocker: no staging credentials.",
    ]

    def stop(self, temp, text, session, retry):
        env = dict(os.environ, QA_EVIDENCE_RETRY_STATE=str(pathlib.Path(temp) / "retry.json"),
                   QA_GATE_EVENTS_FILE=str(pathlib.Path(temp) / "events.jsonl"))
        payload = {"stop_hook_active": retry, "session_id": session, "last_assistant_message": text}
        out = run(["python3", str(EVIDENCE)], env=env, data=json.dumps(payload)).stdout.strip()
        return json.loads(out)["decision"] if out else "none"

    def nudged_turn(self, temp, reply, session):
        self.assertEqual(self.stop(temp, self.FIRST_CLAIM, session, False), "block")
        return self.stop(temp, reply, session, True)

    def test_retry_blocks_once_when_the_nudge_gets_no_packet_and_no_outside_blocker(self):
        with tempfile.TemporaryDirectory() as temp:
            for i, reply in enumerate(self.UNANSWERED):
                self.assertEqual(self.nudged_turn(temp, reply, f"u{i}"), "block", reply)
            self.assertEqual(self.stop(temp, self.UNANSWERED[0], "u0", True), "none", "a third stop must not loop")

    def test_retry_allows_a_packet_or_a_named_outside_blocker(self):
        with tempfile.TemporaryDirectory() as temp:
            for i, reply in enumerate(self.ANSWERED):
                self.assertEqual(self.nudged_turn(temp, reply, f"a{i}"), "none", reply)

    def test_retry_after_another_hooks_block_is_not_checked(self):
        # This hook did not nudge on the first stop (no claim), so the retry belongs to another hook's block.
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(self.stop(temp, "Here is the plan; remaining: run the import.", "c1", False), "allow")
            self.assertEqual(self.stop(temp, "Tests were not run.", "c1", True), "none")
            self.assertEqual(self.stop(temp, "Tests were not run.", "c2", True), "none", "no first stop at all")

    def test_retry_nudge_returns_in_a_later_turn_of_the_same_session(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(self.nudged_turn(temp, "Tests were not run.", "s1"), "block")
            self.assertEqual(self.stop(temp, "Tests were not run.", "s1", True), "none", "bounded within the turn")
            self.assertEqual(self.nudged_turn(temp, "Tests were not run.", "s1"), "block", "a later turn is checked")

    def test_stop_hook_uses_transcript_when_last_message_is_missing(self):
        self.assert_stop_fixture("transcript fallback nudge", opted_in=False, transcript=True,
                                 expected="[qa-evidence]", claim="Done — the workflow is fixed.")

    def assert_stop_fixture(self, label, *, opted_in, transcript, expected, claim):
        with tempfile.TemporaryDirectory() as temp:
            home = pathlib.Path(temp) / "home"
            scripts = home / ".agents/skills/qa-sweep/scripts"
            scripts.mkdir(parents=True)
            shutil.copy2(EVIDENCE, scripts / "evidence-stop.py")
            shutil.copy2(SHIP, scripts / "ship-gate.py")
            repo = pathlib.Path(temp) / "repo"
            repo.mkdir()
            run(["git", "init", "-q", "-b", "main"], cwd=repo)
            if opted_in:
                qa = repo / ".qa"
                qa.mkdir()
                (qa / "config.json").write_text("{}\n")
                (qa / "inventory.jsonl").write_text(json.dumps({
                    "id": "fixture-row", "status": "open", "step": "fixture", "symptom": "fixture"}) + "\n")
            payload = {"cwd": str(repo), "last_assistant_message": claim}
            if transcript:
                path = pathlib.Path(temp) / "codex-rollout.jsonl"
                path.write_text(json.dumps({"type": "response_item", "payload": {
                    "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": claim}]
                }}) + "\n")
                payload.pop("last_assistant_message")
                payload["transcript_path"] = str(path)
            env = dict(os.environ, HOME=str(home))
            response = run(["sh", str(STOP)], env=env, data=json.dumps(payload))
            self.assertIn(expected, response.stdout, label)
            if opted_in:
                self.assertNotIn("[qa-evidence]", response.stdout, label)
            return response.stdout

    def test_codex_trust_only_updates_agent_hooks_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            home = pathlib.Path(temp)
            hooks_dir = home / ".agent-hooks"
            codex_dir = home / ".codex"
            hooks_dir.mkdir()
            codex_dir.mkdir()
            own = hooks_dir / "qa-stop-hook.sh"
            other = home / "third-party-hook.sh"
            own.write_text("#!/bin/sh\n")
            other.write_text("#!/bin/sh\n")
            hooks = codex_dir / "hooks.json"
            hooks.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": str(own), "timeout": 5},
                {"type": "command", "command": str(other), "timeout": 5},
            ]}]}}))
            config = codex_dir / "config.toml"
            config.write_text("")
            env = dict(os.environ, HOME=str(home))
            proc = run(["python3", str(TRUST), "--trust"], env=env)
            self.assertIn("SKIP untrusted hook outside ~/.agent-hooks", proc.stdout)
            state = subprocess.run(["python3", "-c", "import tomllib,sys;print(tomllib.load(open(sys.argv[1],'rb'))['hooks']['state'])", str(config)], capture_output=True, text=True, check=True).stdout
            parsed = ast.literal_eval(state)
            self.assertEqual(len(parsed), 1)
            self.assertIn("trusted_hash", next(iter(parsed.values())))


if __name__ == "__main__":
    unittest.main()
