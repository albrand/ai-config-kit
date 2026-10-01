#!/usr/bin/env python3
"""Stop-time closeout check for coordinators with a scope ledger.

The fleet idle guard nudges a coordinator 30 min after it goes idle with open
purposes. Early stops (status reports, "remains blocked", asking about work
already authorized) are corrected by the user well before that, so this runs
the same predicate when the turn ends:

- the ledger has an open purpose (or a blocked-on-user one the user has since
  answered in this turn), and
- nothing carries the work: no active or pending child, no queued message, no
  background task.

Then the stop is blocked once with the open purposes and the three allowed
outcomes. A coordinator with child threads but no ledger is asked once, per
thread, to record one. Any failure to read state allows the stop.
"""
import datetime
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVENTS = os.environ.get("QA_GATE_EVENTS_FILE") or os.path.expanduser("~/.local/state/agent-quality/events.jsonl")
NUDGED = os.environ.get("CLOSEOUT_NUDGED_FILE") or os.path.expanduser("~/.local/state/agent-quality/closeout-ledger-nudged.json")
BB_TIMEOUT_S = 3.0
TRANSCRIPT_TAIL = 4 * 1024 * 1024
# Inputs bb and the hooks compose; a turn opened by one of these is not the user answering an ask.
MACHINE_INPUT = re.compile(r"^\s*(\[(bb |from |child of|fleet |qa-|scope-)|<)", re.I)
GATE = os.path.join(HERE, "scope-gate.py")


def load_gate():
    spec = importlib.util.spec_from_file_location("scope_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def bb_binary():
    return (os.environ.get("BB_CLI") or shutil.which("bb")
            or "/Applications/bb.app/Contents/Resources/app.asar.unpacked/node_modules/bb-app/host-daemon/dist/bb")


def bb_json(procs):
    """Run bb reads concurrently; None for any that fails or times out."""
    out = {}
    for key, proc in procs.items():
        try:
            stdout, _ = proc.communicate(timeout=BB_TIMEOUT_S)
            out[key] = json.loads(stdout) if proc.returncode == 0 else None
        except Exception:
            proc.kill()
            out[key] = None
    return out


def thread_state(thread, want_self=True):
    bb = bb_binary()
    spawn = lambda *a: subprocess.Popen([bb, *a, "--json"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    procs = {"children": spawn("thread", "list", "--parent-thread", thread)}
    if want_self:
        procs["self"] = spawn("thread", "show", thread)
    return bb_json(procs)


def carried_by(state):
    """Why the work is still moving, or '' when nothing carries it. None when state is unreadable."""
    children, me = state.get("children"), state.get("self")
    if not isinstance(children, list) or not isinstance(me, dict):
        return None
    me = me.get("thread", me)
    active = [c.get("id") for c in children if isinstance(c, dict) and c.get("status") in ("active", "pending")]
    if active:
        return "child thread(s) active: " + ", ".join(map(str, active))
    if (me.get("queuedMessageCount") or 0) > 0:
        return f"{me['queuedMessageCount']} message(s) queued"
    act = me.get("activity") or {}
    running = sum(act.get(k) or 0 for k in ("activeBackgroundCommandCount", "activeBackgroundAgentCount", "activeWorkflowCount"))
    if running > 0:
        return f"{running} background task(s) running"
    return ""


def entry_user_text(entry):
    """(timestamp, text) for a user message entry in a Claude or Codex transcript, else None."""
    if not isinstance(entry, dict):
        return None
    ts = entry.get("timestamp")
    if entry.get("type") == "user":
        content = (entry.get("message") or {}).get("content")
        if isinstance(content, str):
            return ts, content
        if isinstance(content, list):
            texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            return (ts, "\n".join(texts)) if texts else None
        return None
    payload = entry.get("payload")
    if entry.get("type") == "response_item" and isinstance(payload, dict) and payload.get("type") == "message" and payload.get("role") == "user":
        texts = [b.get("text", "") for b in payload.get("content") or [] if isinstance(b, dict)]
        return ts, "\n".join(texts)
    return None


def last_human_input_at(path):
    """Timestamp of the latest user-typed input in the transcript, or None."""
    if not isinstance(path, str) or not path:
        return None
    try:
        with open(os.path.expanduser(path), "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - TRANSCRIPT_TAIL))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            got = entry_user_text(json.loads(line))
        except ValueError:
            continue
        if not got:
            continue
        ts, text = got
        if text.strip() and not MACHINE_INPUT.match(text):
            return ts
    return None


def parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def pending_purposes(ledger, answered_at):
    """Open purposes, plus blocked-on-user ones the user has answered since they were marked."""
    answered = parse_ts(answered_at)
    out = []
    for p in ledger["purposes"]:
        if p["status"] == "open":
            out.append(p)
        elif p["status"] == "blocked-on-user" and answered is not None:
            marked = parse_ts(p.get("status_marked_at"))
            if marked is not None and answered > marked:
                out.append(p)
    return out


def nudge_text(thread, purposes):
    gate = "python3 ~/.agents/skills/scope-ledger/scripts/scope-gate.py"
    lines = ["[scope-closeout] You are stopping with open purposes in your scope ledger, and nothing is carrying them "
             "(no active child, queued message or background task):"]
    for p in purposes:
        text = p["text"] if len(p["text"]) <= 300 else p["text"][:297] + "..."
        state = " (blocked-on-user, answered since)" if p["status"] == "blocked-on-user" else ""
        lines.append(f'- {p["id"]}{state} "{text}"')
    lines += [
        "Do one of these before stopping:",
        "1. Continue the next authorized step now (do it, or dispatch it to a child).",
        f'2. If it is finished: {gate} mark {thread} <Pn> done --evidence "<commit, URL or measurement>"',
        f'3. If only the user can decide: {gate} mark {thread} <Pn> blocked-on-user --ask "<the exact question>". '
        "Only for money, an outward or irreversible effect, credentials, or a genuine ambiguity in the request.",
        "A status report, a summary or an offer to continue is none of these. This is a one-time nudge for this turn.",
    ]
    return "\n".join(lines)


def ledger_nudge_text(thread):
    gate = "python3 ~/.agents/skills/scope-ledger/scripts/scope-gate.py"
    return (
        "[scope-closeout] You coordinate child threads but have no scope ledger, so nothing checks your stops "
        "against what the user asked. Record the user's purposes now, in their exact words: write "
        '{"purposes":[{"id":"P1","text":"<user\'s words>","done_when":"<observable end state>","status":"open"}]} '
        f"to a file and run: {gate} init {thread} --from <file>. Mark finished ones done with evidence. "
        "Then carry on. This is asked once per thread."
    )


def already_nudged(thread):
    try:
        with open(NUDGED, encoding="utf-8") as fh:
            return thread in json.load(fh)
    except (OSError, ValueError, TypeError):
        return False


def remember_nudged(thread):
    try:
        try:
            with open(NUDGED, encoding="utf-8") as fh:
                seen = json.load(fh)
            if not isinstance(seen, list):
                seen = []
        except (OSError, ValueError):
            seen = []
        seen.append(thread)
        os.makedirs(os.path.dirname(NUDGED), mode=0o700, exist_ok=True)
        tmp = NUDGED + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(sorted(set(seen)), fh)
        os.replace(tmp, NUDGED)
    except OSError:
        pass


def log(thread, branch, decision, detail, open_ids=()):
    """Bounded metadata only; never message or purpose text."""
    try:
        event = {
            "schema_version": 1,
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "event": "closeout-stop",
            "thread": thread,
            "provider": os.environ.get("QA_GATE_PROVIDER") or os.environ.get("AGENT_PROVIDER") or "",
            "branch": branch,
            "decision": decision,
            "detail": detail[:120],
            "open": list(open_ids),
        }
        os.makedirs(os.path.dirname(EVENTS), mode=0o700, exist_ok=True)
        with open(EVENTS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
    except Exception:
        pass


def decide(payload, thread, gate, state_reader=thread_state):
    """{'decision': 'block'|'allow', ...}; never raises."""
    allow = lambda why: {"decision": "allow", "why": why}
    if payload.get("stop_hook_active") or payload.get("stopHookActive"):
        return allow("retry after a nudge")
    if not gate.THREAD_ID.match(thread or ""):
        return allow("no bb thread")
    try:
        ledger = gate.read_ledger(thread)
    except gate.LedgerError as e:
        return allow(f"ledger unreadable: {e}")
    if ledger is None:
        if already_nudged(thread):
            return allow("no ledger; already asked")
        state = state_reader(thread, want_self=False)
        children = state.get("children")
        if not isinstance(children, list):
            return allow("no ledger; children unreadable")
        if not [c for c in children if isinstance(c, dict) and not c.get("archivedAt")]:
            return allow("no ledger; not a coordinator")
        remember_nudged(thread)
        log(thread, "no-ledger", "block", "coordinator without ledger")
        return {"decision": "block", "reason": ledger_nudge_text(thread)}
    answered_at = last_human_input_at(payload.get("transcript_path") or payload.get("transcriptPath"))
    pending = pending_purposes(ledger, answered_at)
    if not pending:
        return allow("no open purposes")
    ids = [p["id"] for p in pending]
    carried = carried_by(state_reader(thread))
    if carried is None:
        log(thread, "ledger", "allow", "state unreadable", ids)
        return allow("thread state unreadable")
    if carried:
        log(thread, "ledger", "allow", carried, ids)
        return allow(carried)
    log(thread, "ledger", "block", "nothing carries open purposes", ids)
    return {"decision": "block", "reason": nudge_text(thread, pending)}


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        result = decide(payload, os.environ.get("BB_THREAD_ID", ""), load_gate())
    except Exception as e:
        # A broken check must not strand a turn.
        result = {"decision": "allow", "why": f"error: {type(e).__name__}"}
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
