#!/usr/bin/env python3
"""Fixtures for the scope-ledger closeout check at Stop and its place in the stop chain."""
import datetime
import json
from contextlib import closing
import importlib.util
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SHARED = ROOT.parent / "shared"
CLOSEOUT = SHARED / "scope-ledger/scripts/closeout-stop.py"
SPEC = importlib.util.spec_from_file_location("closeout_stop", CLOSEOUT)
CLOSEOUT_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLOSEOUT_MODULE)
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
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("CREATE TABLE events (thread_id TEXT, type TEXT, data TEXT, created_at INTEGER, "
                       "item_id TEXT, item_kind TEXT)")
            db.execute("CREATE TABLE threads (id TEXT, status TEXT, archived_at INTEGER, parent_thread_id TEXT, "
                       "deleted_at INTEGER)")
            db.execute("CREATE TABLE queued_thread_messages (id TEXT, thread_id TEXT)")
        self.clock = int(time.time() * 1000) - 3600 * 1000
        self.set_state(children=[{"id": "thr_child1", "status": "idle", "archivedAt": None}])

    def event(self, thread, kind, data=None, item_id=None, item_kind=None):
        self.clock += 1000
        with closing(sqlite3.connect(self.db)) as db, db:
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
        with closing(sqlite3.connect(self.db)) as db, db:
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

    def native_transcript(self, *entries):
        """A Claude Code transcript; bb records nothing for a native terminal session's background tasks."""
        path = pathlib.Path(self.tmp.name) / f"native-{len(list(pathlib.Path(self.tmp.name).glob('native-*.jsonl')))}.jsonl"
        path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        return {"transcript_path": str(path)}

    def output(self, task):
        return str(pathlib.Path(self.tmp.name) / f"{task}.output")

    def started(self, task, desc, ts, timed_out=False):
        use = f"toolu_{task}"
        call = {"command": "sh watch.sh", "description": desc}
        call.update({"timeout": 600000} if timed_out else {"run_in_background": True})
        result = {"stdout": "", "backgroundTaskId": task}
        result.update({"timedOutAfterMs": 600000} if timed_out else {})
        said = f"Command running in background with ID: {task}. Output is being written to: {self.output(task)}. You will be notified."
        return [{"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "content": [
                    {"type": "tool_use", "id": use, "name": "Bash", "input": call}]}},
                {"type": "user", "timestamp": ts, "toolUseResult": result,
                 "message": {"role": "user", "content": [{"tool_use_id": use, "type": "tool_result", "content": said}]}}]

    @staticmethod
    def notified(task):
        return (f"<task-notification>\n<task-id>{task}</task-id>\n<status>completed</status>\n"
                f"<summary>Background command completed (exit code 0)</summary>\n</task-notification>")

    def running(self, *entries):
        """Descriptions transcript_background reports, with every output file treated as held by a live shell."""
        path = self.native_transcript(*entries)["transcript_path"]
        return CLOSEOUT_MODULE.transcript_background(path, live=lambda outs: {os.path.realpath(o) for o in outs})

    def test_native_session_transcript_starts_and_ends(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        ts = (now - datetime.timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
        old = (now - datetime.timedelta(hours=25)).isoformat().replace("+00:00", "Z")
        start = self.started("bw1", "serves: P4 — wait for a head", ts)
        self.assertEqual(self.running(*start), ["serves: P4 — wait for a head"])
        # A command moved to the background on timeout has no background flag; its description still counts.
        self.assertEqual(self.running(*self.started("bw3", "serves: P4 — verify", ts, timed_out=True)), ["serves: P4 — verify"])
        ends = {
            "user notification": {"type": "user", "timestamp": ts, "message": {"role": "user", "content": self.notified("bw1")}},
            "queued mid-turn": {"type": "queue-operation", "operation": "enqueue", "timestamp": ts, "content": self.notified("bw1")},
            "queued attachment": {"type": "attachment", "timestamp": ts,
                                  "attachment": {"type": "queued_command", "prompt": self.notified("bw1")}},
            "TaskStop": {"type": "user", "timestamp": ts, "toolUseResult": {
                "message": "Successfully stopped task: bw1 (sh watch.sh)", "task_id": "bw1", "task_type": "local_bash"},
                "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_x", "content": "stopped"}]}},
        }
        for name, end in ends.items():
            with self.subTest(end=name):
                self.assertEqual(self.running(*start, end), [])
        # A tool result that quotes a notification is not one.
        quoted = {"type": "user", "timestamp": ts, "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_y", "content": self.notified("bw1")}]}}
        self.assertEqual(self.running(*start, quoted), ["serves: P4 — wait for a head"])
        # A resumed or restarted process lost its shells; a compaction keeps them.
        session = lambda source: {"type": "attachment", "timestamp": ts, "attachment": {
            "type": "hook_success", "hookName": f"SessionStart:{source}", "hookEvent": "SessionStart"}}
        for source, kept in (("resume", []), ("startup", []), ("compact", ["serves: P4 — wait for a head"])):
            with self.subTest(session=source):
                self.assertEqual(self.running(*start, session(source)), kept)
        # After a compaction the start survives only as a task_status attachment; past the horizon it is lost.
        status = lambda when, state="running": {"type": "attachment", "timestamp": when, "attachment": {
            "type": "task_status", "taskId": "bw2", "taskType": "local_bash", "description": "serves: P4 — wait",
            "status": state, "outputFilePath": self.output("bw2")}}
        self.assertEqual(self.running(status(ts)), ["serves: P4 — wait"])
        self.assertEqual(self.running(status(old)), [])
        self.assertEqual(self.running(status(ts), status(ts, "completed")), [])

    def observes_processes(self):
        """Whether this host lets a process see its own child and the file it holds, checked without the hook's code.

        The verify runner's sandbox hides other processes. There the hook must fail closed (nothing is live, the
        stop is nudged); everywhere else the liveness rule itself is asserted.
        """
        out = self.output("probe")
        with open(out, "w") as fh:
            child = subprocess.Popen(["sleep", "30"], stdout=fh)
        try:
            seen = subprocess.run(["ps", "-o", "ppid=", "-p", str(child.pid)], capture_output=True, text=True).stdout.split()
            if seen != [str(os.getpid())]:
                return False
            held = subprocess.run(["lsof", "-t", "--", out], capture_output=True, text=True).stdout.split()
            return str(child.pid) in held
        except OSError:
            return False
        finally:
            child.kill()
            child.wait()

    def test_native_task_is_live_only_while_this_session_holds_its_output(self):
        # A live shell of this session holds its output open; an ended one doesn't, and an orphan from a crashed
        # session (reparented away from the agent process) is not this session's. Native starts carry only on macOS.
        observable = self.observes_processes()
        carries = observable and sys.platform == "darwin"
        out = self.output("live")
        with open(out, "w") as fh:
            child = subprocess.Popen(["sleep", "30"], stdout=fh)
        try:
            self.assertEqual(CLOSEOUT_MODULE.live_outputs([out], agent=os.getpid()),
                             {os.path.realpath(out)} if carries else set())
        finally:
            child.kill()
            child.wait()
        self.assertEqual(CLOSEOUT_MODULE.live_outputs([out], agent=os.getpid()), set())
        # The agent holding the output open after its shell exited is not a live task, and neither is another
        # descendant that inherited that descriptor: only a holder whose stdout is the file is a task's worker.
        with open(out, "a") as held:
            self.assertEqual(CLOSEOUT_MODULE.live_outputs([out], agent=os.getpid()), set())
            heir = subprocess.Popen(["sleep", "30"], stdout=subprocess.DEVNULL, pass_fds=(held.fileno(),))
            try:
                self.assertEqual(CLOSEOUT_MODULE.live_outputs([out], agent=os.getpid()), set())
            finally:
                heir.kill()
                heir.wait()
        # A grandchild whose stdout is the file (r7), under a direct child whose own stdout is not: it got that
        # stdout from another parent, so it is not the task's root shell.
        nested = subprocess.Popen(["sh", "-c", f'sleep 30 > "{out}" & G=$!; trap "kill $G" TERM; wait'],
                                  stdout=subprocess.DEVNULL)
        try:
            if observable:
                deadline = time.time() + 5
                while not CLOSEOUT_MODULE.file_holders([out])[os.path.realpath(out)] and time.time() < deadline:
                    time.sleep(0.05)
                self.assertTrue(CLOSEOUT_MODULE.file_holders([out])[os.path.realpath(out)])
            self.assertEqual(CLOSEOUT_MODULE.live_outputs([out], agent=os.getpid()), set())
        finally:
            nested.terminate()
            nested.wait()
        # A descendant writing the file only as stderr is not the task's worker either.
        with open(out, "a") as fh:
            child = subprocess.Popen(["sleep", "30"], stdout=subprocess.DEVNULL, stderr=fh)
        try:
            self.assertEqual(CLOSEOUT_MODULE.live_outputs([out], agent=os.getpid()), set())
        finally:
            child.kill()
            child.wait()
        orphan_out = self.output("orphan")
        orphan = int(subprocess.run(["sh", "-c", f'sleep 30 > "{orphan_out}" 2>&1 & echo $!'],
                                    capture_output=True, text=True, check=True).stdout)
        try:
            self.assertEqual(CLOSEOUT_MODULE.live_outputs([orphan_out], agent=os.getpid()), set())
        finally:
            os.kill(orphan, 9)

    def test_process_table_survives_command_lines_that_are_not_utf8(self):
        # A host process with stray bytes in its argv (Linux's ps prints them raw) must not take the table down.
        bin_dir = pathlib.Path(self.tmp.name) / "fakebin"
        bin_dir.mkdir()
        fake = bin_dir / "ps"
        fake.write_bytes(b"#!/bin/sh\nprintf '  101     1 /usr/bin/odd \\377\\376 arg\\n  102   101 claude --flag\\n'\n")
        fake.chmod(0o755)
        saved = os.environ["PATH"]
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{saved}"
        try:
            table = CLOSEOUT_MODULE.process_table()
        finally:
            os.environ["PATH"] = saved
        self.assertEqual(sorted(table), [101, 102])
        self.assertEqual(table[102], (101, "claude --flag"))
        self.assertEqual(CLOSEOUT_MODULE.agent_process(table, pid=102), 102)

    @unittest.skipUnless(sys.platform.startswith("linux"), "PR_SET_CHILD_SUBREAPER is Linux's")
    def test_an_adopted_orphan_carries_nothing_on_linux(self):
        # r8: a subreaper agent adopts an orphan that still has the output as stdout, which makes it a direct child.
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        PR_SET_CHILD_SUBREAPER = 36
        self.assertEqual(libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0), 0)
        out = os.path.realpath(self.output("adopted"))
        try:
            # Its own stdin, or a non-interactive dash on Linux lets the background sleep exit at once.
            orphan = int(subprocess.run(["sh", "-c", f'sleep 30 > "{out}" 2>&1 < /dev/null & echo $!'],
                                        capture_output=True, text=True, check=True).stdout)
            try:
                ppid = subprocess.run(["ps", "-o", "ppid=", "-p", str(orphan)], capture_output=True, text=True).stdout
                self.assertEqual(ppid.split(), [str(os.getpid())])
                if shutil.which("lsof"):
                    deadline = time.time() + 5
                    while not CLOSEOUT_MODULE.file_holders([out])[out] and time.time() < deadline:
                        time.sleep(0.05)
                    self.assertEqual(CLOSEOUT_MODULE.file_holders([out]), {out: {orphan}})
                self.assertEqual(CLOSEOUT_MODULE.live_outputs([out], agent=os.getpid()), set())
            finally:
                os.kill(orphan, 9)
                os.waitpid(orphan, 0)
        finally:
            libc.prctl(PR_SET_CHILD_SUBREAPER, 0, 0, 0, 0)

    def test_native_session_stop_is_carried_only_by_a_live_labelled_task(self):
        self.write_ledger(self.purpose("P4", text="merge root's PRs"))
        self.set_state(children=[])
        ts = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
        # Run the hook under a process named claude, the way Claude Code runs it, with or without a live shell.
        agent = pathlib.Path(self.tmp.name) / "bin" / "claude"
        agent.parent.mkdir()
        agent.symlink_to("/bin/sh")
        carries = self.observes_processes() and sys.platform == "darwin"
        def stop(payload, shell, agent_holds=False, heir=False, reaped=False, grandchild=False):
            out_file = self.output("bw1")
            hold = f'sleep 30 > "{out_file}" & S=$!; ' if shell or reaped else ""
            hold += 'kill $S; wait $S; S=; ' if reaped else ""
            hold += f'exec 3>>"{out_file}"; ' if agent_holds else ""
            hold += 'sleep 30 >/dev/null 2>&1 & S=$!; ' if heir else ""
            hold += (f'sh -c \'sleep 30 > "{out_file}" & G=$!; trap "kill $G" TERM; wait\' >/dev/null 2>&1 & S=$!; '
                     'sleep 1; ') if grandchild else ""
            out = subprocess.run([str(agent), "-c", hold + 'python3 "$0"; R=$?; [ -n "$S" ] && kill $S; exit $R', str(CLOSEOUT)],
                                 input=json.dumps(payload), text=True, capture_output=True, env=self.env(), check=True)
            return json.loads(out.stdout)["decision"]
        labelled = self.native_transcript(*self.started("bw1", "serves: P4 — wait for a head", ts))
        ended = self.native_transcript(*self.started("bw1", "serves: P4 — wait for a head", ts),
                                       {"type": "user", "timestamp": ts, "message": {"role": "user", "content": self.notified("bw1")}})
        # Off macOS (Linux can adopt orphans) and where processes can't be observed (the runner's sandbox, no
        # lsof), even a live labelled shell must not carry.
        self.assertEqual(stop(labelled, shell=True), "allow" if carries else "block")
        # The regression: a crashed session with no SessionStart hook leaves the start with no end and no shell.
        self.assertEqual(stop(labelled, shell=False), "block")
        # The worker was killed and reaped before the stop.
        self.assertEqual(stop(labelled, shell=False, reaped=True), "block")
        # The shell exited but the agent process still holds the output open: still nothing carries.
        self.assertEqual(stop(labelled, shell=False, agent_holds=True), "block")
        # Another descendant of the agent inherited that descriptor (r5): it is not the task's worker.
        self.assertEqual(stop(labelled, shell=False, agent_holds=True, heir=True), "block")
        # A grandchild of the agent has the output as stdout, under a direct child whose stdout is not (r7): the
        # task's root shell is gone, so nothing carries.
        self.assertEqual(stop(labelled, shell=False, grandchild=True), "block")
        # The end record wins over a shell still holding the output.
        self.assertEqual(stop(ended, shell=True), "block")
        self.assertEqual(stop(self.native_transcript(*self.started("bw1", "Wait for CI", ts)), shell=True), "block")

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

    def test_stop_hook_feedback_does_not_answer_a_blocked_purpose(self):
        self.write_ledger(self.purpose(status="blocked-on-user", marked="2026-10-08T12:00:00Z"))
        transcript = SHARED / "scope-ledger/tests/fixtures/stop-hook-self-answer.jsonl"
        self.assertEqual(CLOSEOUT_MODULE.last_human_input_at(str(transcript)), "2026-10-08T11:00:00Z")
        ledger = json.loads((self.ledgers / f"{THREAD}.json").read_text())
        answered = CLOSEOUT_MODULE.pending_purposes(ledger, CLOSEOUT_MODULE.last_human_input_at(str(transcript)))
        self.assertEqual(answered, [])
        self.assertEqual(self.closeout({"transcript_path": str(transcript)})["decision"], "allow")

    def test_harness_entries_are_ignored_but_interrupted_user_text_counts(self):
        cases = (
            ("Stop hook feedback:\n[scope-closeout] P5 remains open", None),
            ("Tool loaded.\n[ToolSearch] Loaded skill", None),
            ("[Image: original 1179x2556, displayed at 923x2000. Multiply coordinates by 1.28]", None),
            ("This session is being continued from a previous conversation that ran out of context. Summary follows.", None),
            ("Base directory for this skill: /Users/example/.agents/skills/demo", None),
            ("[Request interrupted by user]", "2026-10-08T11:00:00Z"),
            ("Please answer the host question", "2026-10-08T11:00:00Z"),
            ("I typed about [Image: original 10x20, displayed at 8x16. Multiply coordinates by 1.25], "
             "This session is being continued from a previous conversation that ran out of context, and "
             "Base directory for this skill: /example.", "2026-10-08T11:00:00Z"),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                transcript = self.transcript(("2026-10-08T11:00:00Z", text))
                self.assertEqual(CLOSEOUT_MODULE.last_human_input_at(transcript), expected)

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
                     "Current E2E remains **NOT RUN**.", "Workflows are **NOT RUN**.",
                     "**Live QA:** NOT RUN.", "**E2E:** NOT RUN."):
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
