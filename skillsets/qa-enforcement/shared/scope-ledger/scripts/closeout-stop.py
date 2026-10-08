#!/usr/bin/env python3
"""Stop-time closeout check for coordinators with a scope ledger.

The fleet idle guard nudges a coordinator 30 min after it goes idle with open
purposes. Early stops (status reports, "remains blocked", asking about work
already authorized) are corrected by the user well before that, so this runs
the same predicate when the turn ends:

- the ledger has an open purpose (or a blocked-on-user one the user has since
  answered in this turn), and
- nothing carries it: no active or pending child whose brief or tells name that
  purpose in `serves:`, no background task of its own whose description names
  it in `serves:`, and no queued message (the next input resumes this thread,
  which then runs the check again).

Then the stop is blocked once with the open purposes and the three allowed
outcomes. A coordinator with child threads but no ledger is asked once, per
thread, to record one. Any failure to read state allows the stop.
"""
import datetime
import importlib.util
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVENTS = os.environ.get("QA_GATE_EVENTS_FILE") or os.path.expanduser("~/.local/state/agent-quality/events.jsonl")
NUDGED = os.environ.get("CLOSEOUT_NUDGED_FILE") or os.path.expanduser("~/.local/state/agent-quality/closeout-ledger-nudged.json")
BACKGROUND_HORIZON_S = 24 * 3600
TRANSCRIPT_TAIL = 4 * 1024 * 1024
BB_DB = os.environ.get("CLOSEOUT_BB_DB") or os.path.expanduser("~/.bb/bb.db")
# Inputs bb and the hooks compose; a turn opened by one of these is not the user answering an ask.
MACHINE_INPUT = re.compile(
    r"^\s*(?:\[(bb |from |child of|fleet |qa-|scope-)|<|Stop hook feedback:|Tool loaded\.)", re.I
)
GATE = os.path.join(HERE, "scope-gate.py")
UNFINISHED = re.compile(
    r"\b(?:(?:workflow[s]?|qa|e2e|end[- ]to[- ]end)(?:\s*:\s*|\s+)(?:(?:are|is|remains?)\s+)?not\s+run|"
    r"P\d+\s+(?:remains?|is|still)\s+open\b|"
    r"(?:remains?|still)\s+incomplete|"
    r"(?:remaining|next\s+steps?)\s*:\s*(?:execute|run|fix|implement|test|verify|finish|complete)\b|"
    r"still\s+need[s]?\b[^\n.!?]{0,120}\b(?:walkthrough|verification|testing|fix|implementation)|"
    r"(?:want\s+me\s+to|if\s+you(?:'d|\s+would)\s+like[,\s]+(?:i\s+can\s+)?|"
    r"say\s+the\s+word[,\s]+(?:and\s+)?(?:i(?:'ll|\s+will)\s+)?)"
    r"\s*(?:fix|implement|prepare|investigate|test|verify|install|continue)\b)",
    re.I,
)


def final_text(payload):
    """Read only the latest assistant message; bound transcript reads and ignore tools."""
    for key in ("text", "last_assistant_message", "lastAssistantMessage"):
        if isinstance(payload.get(key), str) and payload[key]:
            return payload[key]
    path = payload.get("transcript_path") or payload.get("transcriptPath")
    if not isinstance(path, str) or not path:
        return ""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - TRANSCRIPT_TAIL))
            lines = fh.read().decode("utf-8", "replace").splitlines()
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            message = entry.get("message") if entry.get("type") == "assistant" else entry.get("payload", entry)
            if not isinstance(message, dict):
                continue
            if entry.get("type") != "assistant" and message.get("role") != "assistant":
                continue
            if message.get("type") not in (None, "message", "agent_message", "assistant_message"):
                continue
            if message.get("channel") not in (None, "final"):
                continue
            content = message.get("content") or message.get("message") or message.get("text")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "\n".join(p["text"] for p in content if isinstance(p, dict) and isinstance(p.get("text"), str))
    except OSError:
        pass
    return ""


def admits_unfinished_work(payload):
    """A bounded continuation check for solo threads; not a judgment of authorization."""
    text = re.sub(r"```[^\n]*\n.*?```", "", final_text(payload), flags=re.S)
    text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))
    text = re.sub(r'''"[^"\n]*"|“[^”\n]*”|‘[^’\n]*’|(?<!\w)'[^'\n]*'(?!\w)|`[^`\n]*`''', "", text)
    text = re.sub(r"\*\*|__", "", text)
    if re.match(r"\s*Paused as requested\b", text, re.I):
        return False
    return bool(UNFINISHED.search(text))


def solo_nudge_text():
    return (
        "[scope-closeout] Your final message identifies unfinished implementation or workflow verification. "
        "Load finish-the-job and meaningful-tests, then continue every actionable authorized step now, "
        "including preparation and independent checks while an approval is pending. A permission hold "
        "applies only to the action needing it; never apply a permission change without approval. "
        "If every remaining step truly depends on user input, give the exact decision and the evidence "
        "that the authorized preparation is exhausted. Do not replace remaining authorized work with a "
        "status rewrite. This is one continuation check for this turn, not approval to expand scope."
    )


def load_gate():
    spec = importlib.util.spec_from_file_location("scope_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def thread_state(thread, want_self=True):
    """Children and own queue/background state, read-only from bb's store.

    The bb CLI took 4-20 s per call at load ~290 (2026-10-01), past Codex's 5 s Stop-hook budget, so the
    check would always fail open exactly when the fleet is busy. The store answers in milliseconds.
    """
    try:
        db = sqlite3.connect(f"file:{BB_DB}?mode=ro", uri=True, timeout=1.0)
        try:
            children = [{"id": i, "status": s, "archivedAt": a} for i, s, a in db.execute(
                "SELECT id, status, archived_at FROM threads WHERE parent_thread_id = ? AND deleted_at IS NULL", (thread,))]
            state = {"children": children}
            if want_self:
                queued = db.execute("SELECT count(*) FROM queued_thread_messages WHERE thread_id = ?", (thread,)).fetchone()[0]
                # A background task is running while its start has no completion; older starts are treated as lost.
                since = int((datetime.datetime.now(datetime.timezone.utc).timestamp() - BACKGROUND_HORIZON_S) * 1000)
                rows = db.execute(
                    "SELECT s.data FROM events s WHERE s.thread_id = ? AND s.type = 'item/started' "
                    "AND s.item_kind = 'backgroundTask' AND s.created_at > ? AND NOT EXISTS (SELECT 1 FROM events c "
                    "WHERE c.thread_id = s.thread_id AND c.item_id = s.item_id "
                    "AND c.type IN ('item/backgroundTask/completed', 'item/completed'))", (thread, since)).fetchall()
                state["self"] = {"id": thread, "queuedMessageCount": queued,
                                 "background": [task_description(data) for (data,) in rows]}
            return state
        finally:
            db.close()
    except sqlite3.Error:
        return {"children": None, "self": None}


def child_serves(child_ids, serves_pattern):
    """{child: purpose ids its outstanding inputs name in `serves:`}, or None when bb's event store can't be read.

    The scope gate requires every spawn and tell to name the purpose it serves, so a child's inputs say which
    purposes it carries. Only inputs requested after the child's last completed turn are outstanding: a child
    reused for P2 no longer carries the P1 assignment it finished. bb exposes no CLI for a child's inputs; this
    reads its store read-only.
    """
    if not child_ids:
        return {}
    try:
        db = sqlite3.connect(f"file:{BB_DB}?mode=ro", uri=True, timeout=1.0)
        try:
            marks = ",".join("?" * len(child_ids))
            rows = db.execute(
                f"SELECT r.thread_id, r.data FROM events r WHERE r.type = 'client/turn/requested' "
                f"AND r.thread_id IN ({marks}) AND r.created_at > COALESCE((SELECT max(c.created_at) FROM events c "
                f"WHERE c.thread_id = r.thread_id AND c.type = 'turn/completed'), 0)", list(child_ids)).fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return None
    out = {c: set() for c in child_ids}
    for thread, data in rows:
        try:
            items = json.loads(data).get("input") or []
        except (ValueError, AttributeError):
            continue
        for item in items:
            text = item.get("text") if isinstance(item, dict) else None
            if isinstance(text, str):
                out[thread] |= named_purposes(text, serves_pattern)
    return out


def task_description(data):
    try:
        item = json.loads(data).get("item") or {}
        return str(item.get("description") or "")
    except (ValueError, AttributeError):
        return ""


def named_purposes(text, serves_pattern):
    return {pid for group in serves_pattern.findall(text or "") for pid in re.findall(r"P\d+", group)}


def carried_by(state, pending_ids, serves_reader, serves_pattern):
    """(ids carried, why) for the pending purposes; None when thread state is unreadable.

    A queued message is the thread's next input and resumes it at once, so it carries every purpose.
    A background task of its own carries only the purposes its description names in `serves:`: an unrelated
    watcher that never finishes must not hide unattended work. An active child carries only the purposes
    its outstanding inputs were dispatched to serve.
    """
    children, me = state.get("children"), state.get("self")
    if not isinstance(children, list) or not isinstance(me, dict):
        return None
    every = set(pending_ids)
    if (me.get("queuedMessageCount") or 0) > 0:
        return every, f"{me['queuedMessageCount']} message(s) queued"
    carried, why = set(), []
    tasks = me.get("background") or []
    if tasks:
        for desc in tasks:
            carried |= named_purposes(desc, serves_pattern)
        why.append(f"{len(tasks)} background task(s), serving {','.join(sorted(carried)) or 'none'}")
    active = [c.get("id") for c in children if isinstance(c, dict) and c.get("status") in ("active", "pending")]
    if active:
        serves = serves_reader(active)
        if serves is None:
            # Without the link, fall back to the idle guard's rule: any active child carries the work.
            return every, "child thread(s) active (purposes unreadable): " + ", ".join(map(str, active))
        carried |= set().union(*serves.values())
        why.append("child thread(s) active: " + ", ".join(f"{c} serves {','.join(sorted(serves[c])) or 'none'}" for c in active))
    return carried & every, "; ".join(why)


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
             "(no active child or background task naming them in `serves:`, no queued message):"]
    for p in purposes:
        text = p["text"] if len(p["text"]) <= 300 else p["text"][:297] + "..."
        state = " (blocked-on-user, answered since)" if p["status"] == "blocked-on-user" else ""
        lines.append(f'- {p["id"]}{state} "{text}"')
    lines += [
        "Do one of these before stopping:",
        "1. Continue the next authorized step now: do it, dispatch it to a child with `serves: <Pn>`, or start the "
        "background task you will wait on with `serves: <Pn>` in its description.",
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


def log(thread, branch, decision, detail, open_ids=(), session_id=None):
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
        if isinstance(session_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session_id):
            event["session_id"] = session_id
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
        # Native Codex hooks inherit app-server process env, not the separate
        # shell_environment_policy used by tools. The message check needs no
        # BB identity and the native Stop result targets its own session.
        if admits_unfinished_work(payload):
            log("", "no-thread-env", "block", "final message identifies unfinished work",
                session_id=payload.get("session_id"))
            return {"decision": "block", "reason": solo_nudge_text()}
        return allow("no bb thread")
    try:
        ledger = gate.read_ledger(thread)
    except gate.LedgerError as e:
        return allow(f"ledger unreadable: {e}")
    if ledger is None:
        if admits_unfinished_work(payload):
            log(thread, "solo", "block", "final message identifies unfinished work")
            return {"decision": "block", "reason": solo_nudge_text()}
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
    got = carried_by(state_reader(thread), ids, lambda c: child_serves(c, gate.SERVES_P), gate.SERVES_P)
    if got is None:
        log(thread, "ledger", "allow", "state unreadable", ids)
        return allow("thread state unreadable")
    carried, why = got
    unattended = [p for p in pending if p["id"] not in carried]
    if not unattended:
        log(thread, "ledger", "allow", why, ids)
        return allow(why)
    log(thread, "ledger", "block", why or "nothing carries open purposes", [p["id"] for p in unattended])
    return {"decision": "block", "reason": nudge_text(thread, unattended)}


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
