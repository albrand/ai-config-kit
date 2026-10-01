#!/usr/bin/env python3
"""Fixtures for the scope-ledger closeout check at Stop and its place in the stop chain."""
import datetime
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
        self.automations = base / "automations" / "data.db"
        (self.automations.parent / "scripts").mkdir(parents=True)
        with sqlite3.connect(self.automations) as db:
            db.execute("CREATE TABLE automations (id TEXT PRIMARY KEY, enabled INTEGER, trigger_type TEXT, "
                       "next_run_at INTEGER, execution TEXT)")
        # The daily measurement that writes the outputs the wait tests wait on.
        self.add_producer("auto_fixture", writes=[base / "awaited-output.md", base / "remeasure.md"])

    def add_producer(self, aid, writes=(), enabled=1, trigger="schedule", next_run_days=1, mode="script"):
        """A bb automation; a script one names its outputs in its script file, an agent one in its prompt."""
        names = " ".join(str(w) for w in writes)
        next_run = int((time.time() + next_run_days * 86400) * 1000)
        if mode == "script":
            folder = self.automations.parent / "scripts" / aid
            folder.mkdir(exist_ok=True)
            (folder / "measure.py").write_text(f"OUT = {names!r}\n")
            execution = {"mode": "script", "scriptFile": "measure.py", "interpreter": "python3"}
        else:
            execution = {"mode": "agent", "prompt": f"Run the measurement and write {names}"}
        with sqlite3.connect(self.automations) as db:
            db.execute("INSERT OR REPLACE INTO automations VALUES (?, ?, ?, ?, ?)",
                       (aid, enabled, trigger, next_run, json.dumps(execution)))

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
                    CLOSEOUT_BB_DB=str(self.db), SCOPE_AUTOMATIONS_DB=str(self.automations))

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

    def gate_cli(self, *args, awaited=True):
        """Run scope-gate.py; a `wait` names the fixture producer's output unless the test passes its own."""
        gate = SHARED / "scope-ledger/scripts/scope-gate.py"
        if args and args[0] == "wait" and awaited:
            if "--ends-when-file" not in args:
                args = (*args, "--ends-when-file", str(pathlib.Path(self.tmp.name) / "awaited-output.md"))
            if "--producer" not in args:
                args = (*args, "--producer", "auto_fixture")
        return subprocess.run(["python3", str(gate), *args], text=True, capture_output=True, env=self.env())

    # Review r3: a wait rests on a scheduled automation that writes the output, not on the agent's word.
    # Work the agent could do now has no producer, so it can't wait and is still nudged; a purpose that
    # really waits on scheduled data stays quiet, until its producer stops qualifying.
    def test_only_data_a_scheduled_automation_produces_can_be_waited_on(self):
        self.write_ledger(self.purpose("P5"), self.purpose("P6", text="ship the docs"))
        base = pathlib.Path(self.tmp.name)
        docs = str(base / "docs-shipped.md")
        soon = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=5)).strftime("%Y-%m-%d")
        self.add_producer("auto_unrelated", writes=[base / "other.md"])
        self.add_producer("auto_off", writes=[docs], enabled=0)
        self.add_producer("auto_manual", writes=[docs], trigger="manual")
        self.add_producer("auto_late", writes=[docs], next_run_days=9)
        for label, producer, why in [("no producer", None, "--producer"),
                                     ("unknown automation", "auto_missing", "no automation"),
                                     ("does not write the output", "auto_unrelated", "does not name"),
                                     ("disabled", "auto_off", "disabled"),
                                     ("not scheduled", "auto_manual", "not scheduled"),
                                     ("runs after the date", "auto_late", "after the wait ends")]:
            args = ["wait", THREAD, "P6", "--until", soon, "--on", "the docs", "--ends-when-file", docs]
            refused = self.gate_cli(*args, *(["--producer", producer] if producer else []), awaited=False)
            self.assertNotEqual(refused.returncode, 0, label)
            self.assertIn(why, refused.stderr, label)
        # An agent-mode automation names its output in the prompt.
        self.add_producer("auto_agent", writes=[base / "remeasure.md"], mode="agent")
        ok = self.gate_cli("wait", THREAD, "P5", "--until", soon, "--on", "the strict re-measure",
                           "--ends-when-file", str(base / "remeasure.md"), "--producer", "auto_agent")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        nudged = self.closeout()
        self.assertEqual(nudged["decision"], "block")
        self.assertIn('P6 "ship the docs"', nudged["reason"])
        self.assertNotIn("P5 ", nudged["reason"])
        # The producer is disabled after the wait was set: the purpose is open work again.
        self.add_producer("auto_agent", writes=[base / "remeasure.md"], mode="agent", enabled=0)
        self.assertIn("P5 ", self.closeout()["reason"])

    # Review r2: a wait must name the output it waits for, and holds only until the user speaks.
    def test_wait_needs_an_output_and_yields_to_the_user(self):
        self.write_ledger(self.purpose("P6", text="ship the docs"))
        soon = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=5)).strftime("%Y-%m-%d")
        bare = self.gate_cli("wait", THREAD, "P6", "--until", soon, "--on", "the daily measurement",
                             "--producer", "auto_fixture", awaited=False)
        self.assertNotEqual(bare.returncode, 0)
        self.assertIn("--ends-when-file", bare.stderr)
        self.assertEqual(self.gate_cli("wait", THREAD, "P6", "--until", soon, "--on", "the daily measurement").returncode, 0)
        self.assertEqual(self.closeout()["decision"], "allow")
        # Through the real stop chain: the user typing after the wait puts the purpose back under the check.
        self.install_chain()
        later = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        transcript = self.transcript((later, "then handle it! why did you stop?"))
        payload = {"cwd": str(self.repo), "last_assistant_message": "Waiting on data.", "transcript_path": transcript}
        out = subprocess.run(["sh", str(STOP)], input=json.dumps(payload), text=True, capture_output=True,
                             env=self.env(), check=True).stdout
        reason = json.loads(out)["reason"]
        self.assertIn("[scope-closeout]", reason)
        self.assertIn('P6 "ship the docs"', reason)

    # The ledger was already self-attested: blocked-on-user with any ask silences a purpose with no cap.
    # A wait is narrower: capped, tied to an output a scheduled automation writes, and lifted by the user's next message.
    def test_blocked_on_user_was_already_an_unbounded_self_attested_silence(self):
        self.write_ledger(self.purpose("P6", text="ship the docs"))
        self.assertEqual(self.gate_cli("mark", THREAD, "P6", "blocked-on-user", "--ask", "anything").returncode, 0)
        self.assertEqual(self.closeout()["decision"], "allow")

    # A purpose that can only move when data arrives is not nudged on every stop until then.
    def test_waiting_purpose_is_quiet_until_its_date(self):
        self.write_ledger(self.purpose("P5"), self.purpose("P6", text="ship the docs"))
        soon = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=17)).strftime("%Y-%m-%d")
        done = self.gate_cli("wait", THREAD, "P5", "--until", soon, "--on", "1,700 post-gate done-claims for the strict re-measure")
        self.assertEqual(done.returncode, 0, done.stderr)
        nudged = self.closeout()
        self.assertEqual(nudged["decision"], "block")
        self.assertIn("P6", nudged["reason"])
        self.assertNotIn("P5 ", nudged["reason"])
        self.gate_cli("mark", THREAD, "P6", "done", "--evidence", "fixture")
        self.assertEqual(self.closeout()["decision"], "allow")
        # Once the date passes the purpose is open work again.
        ledger = json.loads((self.ledgers / f"{THREAD}.json").read_text())
        ledger["purposes"][0]["waiting"]["until"] = "2026-01-01T00:00:00Z"
        (self.ledgers / f"{THREAD}.json").write_text(json.dumps(ledger))
        self.assertIn("P5", self.closeout()["reason"])

    def test_wait_refuses_past_far_or_unexplained_dates(self):
        self.write_ledger(self.purpose("P5"), self.purpose("P6", status="done"))
        far = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=45)).strftime("%Y-%m-%d")
        soon = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=3)).strftime("%Y-%m-%d")
        for label, args in [("past date", ["--until", "2026-01-01", "--on", "data"]),
                            ("beyond 30 days", ["--until", far, "--on", "data"]),
                            ("no reason", ["--until", soon]),
                            ("not a date", ["--until", "next week", "--on", "data"])]:
            self.assertNotEqual(self.gate_cli("wait", THREAD, "P5", *args).returncode, 0, label)
        self.assertNotEqual(self.gate_cli("wait", THREAD, "P6", "--until", soon, "--on", "data").returncode, 0, "done purpose")
        # Any mark clears a wait, so a wait can't outlive a status change.
        self.assertEqual(self.gate_cli("wait", THREAD, "P5", "--until", soon, "--on", "data").returncode, 0)
        self.gate_cli("mark", THREAD, "P5", "open")
        self.assertNotIn("waiting", json.loads((self.ledgers / f"{THREAD}.json").read_text())["purposes"][0])

    # Review r1: a wait is not a renewable snooze, and arrival ends it before the date.
    def test_waits_cannot_be_renewed_past_the_cap(self):
        self.write_ledger(self.purpose("P5"))
        day = lambda n: (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=n)).strftime("%Y-%m-%d")
        self.assertEqual(self.gate_cli("wait", THREAD, "P5", "--until", day(20), "--on", "data").returncode, 0)
        # A renewal inside the 30-day span from the first wait is allowed; one past it is refused.
        self.assertEqual(self.gate_cli("wait", THREAD, "P5", "--until", day(28), "--on", "data").returncode, 0)
        renewed = self.gate_cli("wait", THREAD, "P5", "--until", day(35), "--on", "data")
        self.assertNotEqual(renewed.returncode, 0)
        self.assertIn("first wait", renewed.stderr)
        # Re-opening the purpose clears the wait but not its history, so mark-then-wait can't reset the cap.
        self.gate_cli("mark", THREAD, "P5", "open")
        self.assertNotEqual(self.gate_cli("wait", THREAD, "P5", "--until", day(35), "--on", "data").returncode, 0)
        self.assertEqual(self.closeout()["decision"], "block")

    def test_arrival_ends_the_wait_before_its_date(self):
        self.write_ledger(self.purpose("P5"))
        arrival = pathlib.Path(self.tmp.name) / "remeasure.md"
        soon = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=10)).strftime("%Y-%m-%d")
        self.assertNotEqual(self.gate_cli("wait", THREAD, "P5", "--until", soon, "--on", "data",
                                          "--ends-when-file", "relative.md").returncode, 0)
        self.assertEqual(self.gate_cli("wait", THREAD, "P5", "--until", soon, "--on", "the strict re-measure",
                                       "--ends-when-file", str(arrival)).returncode, 0)
        self.assertEqual(self.closeout()["decision"], "allow")
        arrival.write_text("results\n")
        nudged = self.closeout()
        self.assertEqual(nudged["decision"], "block")
        self.assertIn("P5", nudged["reason"])
        # Waiting on something that has already arrived is refused.
        self.gate_cli("mark", THREAD, "P5", "open")
        self.assertNotEqual(self.gate_cli("wait", THREAD, "P5", "--until", soon, "--on", "data",
                                          "--ends-when-file", str(arrival)).returncode, 0)

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
        self.assertNotIn("[scope-closeout]", claim)
        status = self.stop_chain("Here is where things stand. I haven't started the next part.")
        self.assertIn("[scope-closeout]", status)
        self.assertEqual(json.loads(status)["decision"], "block")

    def test_stop_chain_without_the_check_installed_still_runs(self):
        shutil.copytree(SHARED / "qa-sweep", self.home / ".agents/skills/qa-sweep")
        self.write_ledger(self.purpose())
        self.assertEqual(self.stop_chain("Here is where things stand.").strip(), "")


if __name__ == "__main__":
    unittest.main()
