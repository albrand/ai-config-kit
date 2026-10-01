#!/usr/bin/env python3
"""Fixtures for the scope-ledger closeout check at Stop and its place in the stop chain."""
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import tempfile
import time
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT.parent / "shared"
CLOSEOUT = SHARED / "scope-ledger/scripts/closeout-stop.py"
STOP = ROOT / "qa-stop-hook.sh"
THREAD = "thr_fixturecoord"
PURPOSE = "i ask for overall hardening on skills and directives so we can rely more on agent QAing things"

class CloseoutStopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name)
        self.home = base / "home"
        self.home.mkdir()
        self.ledgers = base / "scope"
        self.ledgers.mkdir()
        self.events = base / "events.jsonl"
        self.nudged = base / "nudged.json"
        self.repo = base / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo, check=True)
        self.db = base / "bb.db"
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TABLE events (thread_id TEXT, type TEXT, data TEXT, created_at INTEGER, "
                       "item_id TEXT, item_kind TEXT)")
            db.execute("CREATE TABLE threads (id TEXT, status TEXT, archived_at INTEGER, parent_thread_id TEXT, "
                       "deleted_at INTEGER)")
            db.execute("CREATE TABLE queued_thread_messages (id TEXT, thread_id TEXT)")
        self.clock = int(time.time() * 1000) - 3600 * 1000
        self.set_state(children=[{"id": "thr_child1", "status": "idle", "archivedAt": None}])

    def event(self, thread, kind, data=None, item_id=None, item_kind=None):
        self.clock += 1000
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
                       (thread, kind, json.dumps(data or {}), self.clock, item_id, item_kind))

    def dispatch(self, child, text):
        self.event(child, "client/turn/requested", {"source": "spawn", "input": [{"type": "text", "text": text}]})

    def complete_turn(self, child):
        self.event(child, "turn/completed")

    def tearDown(self):
        self.tmp.cleanup()

    def env(self):
        return dict(os.environ, HOME=str(self.home), SCOPE_LEDGER_DIR=str(self.ledgers), BB_THREAD_ID=THREAD,
                    QA_GATE_EVENTS_FILE=str(self.events), CLOSEOUT_NUDGED_FILE=str(self.nudged),
                    CLOSEOUT_BB_DB=str(self.db))

    def set_state(self, children=None, queued=0, background=None):
        with sqlite3.connect(self.db) as db:
            if children is not None:
                db.execute("DELETE FROM threads WHERE parent_thread_id = ?", (THREAD,))
                for c in children:
                    db.execute("INSERT INTO threads VALUES (?, ?, ?, ?, NULL)",
                               (c["id"], c["status"], c.get("archivedAt"), THREAD))
            db.execute("DELETE FROM queued_thread_messages WHERE thread_id = ?", (THREAD,))
            for n in range(queued):
                db.execute("INSERT INTO queued_thread_messages VALUES (?, ?)", (f"q{n}", THREAD))
            db.execute("DELETE FROM events WHERE thread_id = ? AND item_kind = 'backgroundTask'", (THREAD,))
        for n, desc in enumerate(background or []):
            self.event(THREAD, "item/started", {"item": {"type": "backgroundTask", "id": f"bg{n}", "description": desc}},
                       item_id=f"bg{n}", item_kind="backgroundTask")

    def write_ledger(self, *purposes):
        (self.ledgers / f"{THREAD}.json").write_text(json.dumps({
            "thread_id": THREAD, "purposes": list(purposes), "accepted_revisions": []}))

    def purpose(self, pid="P5", status="open", marked="2026-09-30T20:00:00Z", text=PURPOSE):
        return {"id": pid, "text": text, "done_when": "", "status": status, "evidence": [],
                "status_marked_at": marked, "ask": "Which host?" if status == "blocked-on-user" else None}

    def transcript(self, *user_inputs):
        path = pathlib.Path(self.tmp.name) / "transcript.jsonl"
        rows = [{"type": "user", "timestamp": ts, "message": {"role": "user", "content": text}} for ts, text in user_inputs]
        rows.append({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Status."}]}})
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        return str(path)

    def closeout(self, payload=None):
        out = subprocess.run(["python3", str(CLOSEOUT)], input=json.dumps(payload or {}), text=True,
                             capture_output=True, env=self.env(), check=True)
        return json.loads(out.stdout)

    # The regression this exists for: a coordinator reported "I haven't started it" with P5 open and no child running.
    def test_open_purpose_with_nothing_running_blocks_once(self):
        self.write_ledger(self.purpose("P1", "done"), self.purpose())
        result = self.closeout({"last_assistant_message": "That's a bigger change. I haven't started it."})
        self.assertEqual(result["decision"], "block")
        self.assertIn("[scope-closeout]", result["reason"])
        self.assertIn("P5", result["reason"])
        self.assertNotIn("P1 ", result["reason"])
        self.assertIn("blocked-on-user", result["reason"])
        self.assertEqual(self.closeout({"stop_hook_active": True})["decision"], "allow")

    def test_work_carried_elsewhere_allows(self):
        self.write_ledger(self.purpose())
        self.dispatch("thr_c", "[child of @thread:thr_fixturecoord] serves: P5 — run the measurement")
        for label, state in [("active child serving P5", dict(children=[{"id": "thr_c", "status": "active"}])),
                             ("pending child serving P5", dict(children=[{"id": "thr_c", "status": "pending"}])),
                             ("queued message", dict(children=[], queued=1)),
                             ("background task serving P5", dict(children=[], background=["serves: P5 — full suite"]))]:
            self.set_state(**state)
            self.assertEqual(self.closeout()["decision"], "allow", label)

    # Review r1: P1's active worker must not hide an unattended P2.
    def test_child_carries_only_the_purposes_it_serves(self):
        self.write_ledger(self.purpose("P1", text="ship the fix"), self.purpose("P2", text="Finish authorized QA"))
        self.dispatch("thr_w1", "[child of @thread:thr_fixturecoord] serves: P1 — implement the fix")
        self.set_state(children=[{"id": "thr_w1", "status": "active"}])
        nudged = self.closeout()
        self.assertEqual(nudged["decision"], "block")
        self.assertIn('P2 "Finish authorized QA"', nudged["reason"])
        self.assertNotIn("ship the fix", nudged["reason"])
        self.assertEqual(self.closeout({"stop_hook_active": True})["decision"], "allow")
        # The coordinator dispatches P2: both purposes are carried, the stop is allowed.
        self.dispatch("thr_w2", "[child of @thread:thr_fixturecoord] serves: P2 — run the QA walk")
        self.set_state(children=[{"id": "thr_w1", "status": "active"}, {"id": "thr_w2", "status": "active"}])
        self.assertEqual(self.closeout()["decision"], "allow")
        # A later tell can add a purpose to a running child.
        self.set_state(children=[{"id": "thr_w1", "status": "active"}])
        self.dispatch("thr_w1", "serves: P2 — also run the QA walk when the fix lands")
        self.assertEqual(self.closeout()["decision"], "allow")
        # The workers finish (bb resumes the coordinator) with both purposes still open: the next stop is checked again.
        self.set_state(children=[{"id": "thr_w1", "status": "idle"}, {"id": "thr_w2", "status": "idle"}])
        resumed = self.closeout()
        self.assertEqual(resumed["decision"], "block")
        self.assertIn("P1", resumed["reason"])
        self.assertIn("P2", resumed["reason"])

    # Review r2: a child reused for P2 no longer carries the P1 assignment it finished.
    def test_finished_assignment_does_not_carry_after_reuse(self):
        self.write_ledger(self.purpose("P1", text="ship the fix"), self.purpose("P2", text="Finish authorized QA"))
        self.dispatch("thr_w1", "[child of @thread:thr_fixturecoord] serves: P1 — implement the fix")
        self.complete_turn("thr_w1")
        self.dispatch("thr_w1", "serves: P2 — now run the QA walk")
        self.set_state(children=[{"id": "thr_w1", "status": "active"}])
        nudged = self.closeout()
        self.assertEqual(nudged["decision"], "block")
        self.assertIn('P1 "ship the fix"', nudged["reason"])
        self.assertNotIn("Finish authorized QA", nudged["reason"])
        self.assertEqual(self.closeout({"stop_hook_active": True})["decision"], "allow")
        # Positive control: both assignments outstanding in the running turn.
        self.dispatch("thr_w1", "serves: P1 — and land the fix follow-up in the same pass")
        self.assertEqual(self.closeout()["decision"], "allow")

    # Review r3: an unrelated unfinished background task must not hide unattended work.
    def test_background_task_carries_only_the_purposes_it_names(self):
        self.write_ledger(self.purpose("P2", text="Finish authorized QA"))
        self.set_state(children=[], background=["Wait for the Hermes verdict"])
        nudged = self.closeout()
        self.assertEqual(nudged["decision"], "block")
        self.assertIn('P2 "Finish authorized QA"', nudged["reason"])
        self.assertEqual(self.closeout({"stop_hook_active": True})["decision"], "allow")
        # Positive control: the coordinator waits on background work it labels as serving P2.
        self.set_state(children=[], background=["Wait for the Hermes verdict", "serves: P2 — run the QA walk"])
        self.assertEqual(self.closeout()["decision"], "allow")

    def test_child_with_no_serves_line_carries_nothing(self):
        self.write_ledger(self.purpose())
        self.dispatch("thr_c", "do some unrelated cleanup")
        self.set_state(children=[{"id": "thr_c", "status": "active"}])
        self.assertEqual(self.closeout()["decision"], "block")

    def test_blocked_on_user_stays_quiet_until_the_user_answers(self):
        self.write_ledger(self.purpose(status="blocked-on-user", marked="2026-09-30T20:00:00Z"))
        self.assertEqual(self.closeout()["decision"], "allow")
        before = self.transcript(("2026-09-30T19:00:00Z", "please do it"))
        self.assertEqual(self.closeout({"transcript_path": before})["decision"], "allow")
        machine = self.transcript(("2026-09-30T21:00:00Z", "[bb system]\n\n@thread:thr_x completed"))
        self.assertEqual(self.closeout({"transcript_path": machine})["decision"], "allow")
        answered = self.transcript(("2026-09-30T21:00:00Z", "then you need to handle it!!!!"))
        result = self.closeout({"transcript_path": answered})
        self.assertEqual(result["decision"], "block")
        self.assertIn("answered since", result["reason"])

    def test_finished_ledger_allows(self):
        self.write_ledger(self.purpose(status="done"))
        self.assertEqual(self.closeout()["decision"], "allow")

    def test_unreadable_state_allows(self):
        self.write_ledger(self.purpose())
        self.db.write_text("not a database")
        self.assertEqual(self.closeout()["decision"], "allow")
        (self.ledgers / f"{THREAD}.json").write_text("{not json")
        self.assertEqual(self.closeout()["decision"], "allow")

    def test_coordinator_without_ledger_is_asked_once(self):
        first = self.closeout()
        self.assertEqual(first["decision"], "block")
        self.assertIn("init " + THREAD, first["reason"])
        self.assertEqual(self.closeout()["decision"], "allow")

    def test_thread_without_children_or_ledger_allows(self):
        self.set_state(children=[{"id": "thr_old", "status": "idle", "archivedAt": 1790000000000}])
        self.assertEqual(self.closeout()["decision"], "allow")

    def test_solo_agent_cannot_end_with_unrun_work_and_no_ledger(self):
        self.set_state(children=[])
        text = "Implemented; workflow NOT RUN; remaining: execute import, sync and restore."
        result = self.closeout({"last_assistant_message": text})
        self.assertEqual(result["decision"], "block")
        self.assertIn("authorized", result["reason"])
        self.assertIn("approval", result["reason"])

    def test_solo_screenshot_status_requires_continuation_check(self):
        self.set_state(children=[])
        text = ("Local changes are finished. M2 remains incomplete: Administrator import, sync "
                "and restore workflows are NOT RUN. To proceed, approve changing Zendesk OAuth.")
        self.assertEqual(self.closeout({"last_assistant_message": text})["decision"], "block")

    def test_solo_clear_permission_request_does_not_require_extra_work(self):
        self.set_state(children=[])
        text = "All authorized local preparation is complete. Approve broadening OAuth read access."
        self.assertEqual(self.closeout({"last_assistant_message": text})["decision"], "allow")

    def test_solo_formatted_qa_and_e2e_reports_require_a_continuation_check(self):
        self.set_state(children=[])
        for text in ("**Live QA NOT RUN:** The administrator save, reload and complete journey is pending.",
                     "Current E2E remains **NOT RUN**.", "Workflows are **NOT RUN**."):
            with self.subTest(text=text):
                self.assertEqual(self.closeout({"last_assistant_message": text})["decision"], "block")

    def test_solo_explicit_open_purpose_requires_a_continuation_check(self):
        self.set_state(children=[])
        self.assertEqual(self.closeout({"last_assistant_message": "P5 remains open; accepted work was not reopened."})["decision"], "block")

    def test_solo_requested_pause_preserves_the_user_stop(self):
        self.set_state(children=[])
        text = "Paused as requested. Next step: run the pending workflow checks when you resume."
        self.assertEqual(self.closeout({"last_assistant_message": text})["decision"], "allow")

    def test_solo_offer_checks_existing_authorization(self):
        self.set_state(children=[])
        for text in ("Want me to implement the fix?", "If you'd like, I can investigate it.",
                     "Say the word and I'll continue."):
            with self.subTest(text=text):
                result = self.closeout({"last_assistant_message": text})
                self.assertEqual(result["decision"], "block")
                self.assertIn("not approval to expand scope", result["reason"])

    def test_solo_fenced_examples_and_tool_output_do_not_trigger(self):
        self.set_state(children=[])
        text = "Example:\n```text\nImplemented; workflow NOT RUN; remaining: run import.\n```"
        self.assertEqual(self.closeout({"last_assistant_message": text})["decision"], "allow")
        transcript = pathlib.Path(self.tmp.name) / "mixed.jsonl"
        transcript.write_text("\n".join(json.dumps(entry) for entry in [
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "channel": "final",
                "content": [{"type": "output_text", "text": "Please approve the access change."}]}},
            {"type": "response_item", "payload": {"type": "function_call_output",
                "output": "Implemented; workflow NOT RUN; remaining: run import."}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "channel": "analysis",
                "content": [{"type": "output_text", "text": "Import still needs a walkthrough."}]}}
        ]) + "\n")
        self.assertEqual(self.closeout({"transcript_path": str(transcript)})["decision"], "allow")

    def test_solo_quoted_example_is_not_a_live_unfinished_task(self):
        self.set_state(children=[])
        text = "The old report said:\n> Implemented; workflow NOT RUN; remaining: run the import."
        self.assertEqual(self.closeout({"last_assistant_message": text})["decision"], "allow")

    def test_solo_inline_quotes_do_not_create_unfinished_work(self):
        self.set_state(children=[])
        for quoted in ('"Want me to implement the fix?"', '“Want me to implement the fix?”',
                       "'Want me to implement the fix?'", '‘Want me to implement the fix?’',
                       '`Want me to implement the fix?`'):
            with self.subTest(quoted=quoted):
                text = f"The transcript quoted: {quoted}; all authorized work is complete."
                self.assertEqual(self.closeout({"last_assistant_message": text})["decision"], "allow")
        self.assertEqual(self.closeout({"last_assistant_message": "If you'd like, I can implement it."})["decision"], "block")

    def test_solo_transcript_fallback_checks_final_message(self):
        self.set_state(children=[])
        transcript = pathlib.Path(self.tmp.name) / "solo.jsonl"
        transcript.write_text(json.dumps({"type": "response_item", "payload": {
            "type": "message", "role": "assistant", "channel": "final", "content": [
                {"type": "output_text", "text": "Import, sync and restore still need their live walkthrough."}
            ]}}) + "\n")
        self.assertEqual(self.closeout({"transcript_path": str(transcript)})["decision"], "block")

    def test_solo_safety_retry_remains_bounded(self):
        self.set_state(children=[])
        text = "Implemented; workflow NOT RUN; remaining: run import."
        self.assertEqual(self.closeout({"last_assistant_message": text, "stop_hook_active": True})["decision"], "allow")

    def test_native_hook_without_shell_thread_env_still_checks_unfinished_work(self):
        self.install_chain()
        env = self.env()
        env.pop("BB_THREAD_ID", None)
        payload = {"cwd": str(self.repo), "session_id": "fixture-native-session",
                   "last_assistant_message": "Workflow NOT RUN; remaining: run the continuation acceptance checks."}
        result = subprocess.run(["sh", str(STOP)], input=json.dumps(payload), text=True,
                                capture_output=True, env=env, check=True)
        self.assertEqual(json.loads(result.stdout)["decision"], "block")
        events = [json.loads(line) for line in self.events.read_text().splitlines()]
        self.assertEqual(events[-1]["session_id"], "fixture-native-session")
        payload["stop_hook_active"] = True
        retry = subprocess.run(["sh", str(STOP)], input=json.dumps(payload), text=True,
                               capture_output=True, env=env, check=True)
        self.assertEqual(retry.stdout.strip(), "")

    def test_events_hold_ids_not_text(self):
        self.write_ledger(self.purpose())
        self.closeout()
        rows = [json.loads(line) for line in self.events.read_text().splitlines()]
        self.assertEqual([(r["event"], r["decision"], r["open"]) for r in rows], [("closeout-stop", "block", ["P5"])])
        self.assertNotIn("hardening", self.events.read_text())

    def install_chain(self):
        for skill in ("qa-sweep", "scope-ledger"):
            shutil.copytree(SHARED / skill, self.home / ".agents/skills" / skill)

    def stop_chain(self, text):
        payload = {"cwd": str(self.repo), "last_assistant_message": text}
        return subprocess.run(["sh", str(STOP)], input=json.dumps(payload), text=True, capture_output=True,
                              env=self.env(), check=True).stdout

    def test_stop_chain_gives_one_nudge_per_turn(self):
        self.install_chain()
        self.write_ledger(self.purpose())
        claim = self.stop_chain("Done — the workflow is fixed.")
        self.assertIn("[qa-evidence]", claim)
        self.assertIn("[scope-closeout]", claim)
        status = self.stop_chain("Here is where things stand. I haven't started the next part.")
        self.assertIn("[scope-closeout]", status)
        self.assertEqual(json.loads(status)["decision"], "block")

    def test_stop_chain_without_the_check_installed_still_runs(self):
        shutil.copytree(SHARED / "qa-sweep", self.home / ".agents/skills/qa-sweep")
        self.write_ledger(self.purpose())
        self.assertEqual(self.stop_chain("Here is where things stand.").strip(), "")


if __name__ == "__main__":
    unittest.main()
