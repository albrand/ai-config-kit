#!/usr/bin/env python3
"""One-turn nudge when a final message stops with runnable work still open."""
import importlib.util
import json
import os
import re
import sys
import time


OWNER_LINE = re.compile(r"^[\s>*-]*(?:NEEDS-OWNER:|STATUS:\s*needs-owner)", re.IGNORECASE | re.MULTILINE)
PROMISE = re.compile(
    r"\b(?:i(?:'ll|\s+will|'m\s+going\s+to|\s+am\s+going\s+to)|we(?:'ll|\s+will)|next,?\s+i\s+will|next\s+up|"
    r"let\s+me\s+(?!know\b)[a-z]+|let\s+me\s+know\s+(?:when|once|as\s+soon\s+as))\b",
    re.IGNORECASE,
)
# A conditional counts only when it names an outside event finishing or arriving, not more of our own work.
CONDITIONAL = re.compile(
    # The event must come before the clause's comma and before any "I"/"we": in "After reviewing the diff,
    # I will post the review", posting is our own work, not something we wait for.
    r"\b(?:when|once|as\s+soon\s+as|after)\s+(?!(?:i|we)\b|i'|we')(?:(?!\b(?:i|we)\b|\bi'|\bwe')[^.;!?,]){0,60}?\b(?:(?:arriv|finish|land|comes?\s+back|"
    r"return|complet|pass|green|done|clean|merged|report|repl|respond|ready|exit|end)\w*"
    # verb forms only: "deliverables", "sentence" or "postpone" are not events
    r"|(?:sends?|sent|posts?|posted|delivers?|delivered)\b)",
    re.IGNORECASE,
)
STATE_WAIT = re.compile(
    r"\b(?:still\s+(?:running|in\s+progress|pending)|in\s+progress|waiting\s+(?:on|for)|watch(?:ing|er)|notif\w*|"
    r"(?:monitor|child|worker)\s+will)\b",
    re.IGNORECASE,
)
WAITING = re.compile(f"(?:{CONDITIONAL.pattern})|(?:{STATE_WAIT.pattern})", re.IGNORECASE)
CLAUSE = re.compile(
    r"(?<=[.!?])\s+|\n|;|,?\s*\b(?:but|also|meanwhile|in\s+the\s+meantime)\b|,?\s*\b(?:and\s+then|then|and)\s+(?=(?:i|we)\b)"
    # A conditional after a comma starts its own clause, so it cannot excuse a promise made before it.
    r"|,\s*(?:and\s+|then\s+)?(?=(?:when|once|after|as\s+soon\s+as)\b)",
    re.IGNORECASE,
)
UNFINISHED = re.compile(
    r"\b(?:remain(?:s|ing)?\s+(?:unrun|untested|unverified|undone|to\s+(?:run|do))|"
    r"(?:not|never|\w+n't)\s+(?:yet\s+)?(?:been\s+)?(?:yet\s+)?(?:run|tested|verified|done|finished)|"
    r"needs?\s+to\s+be\s+(?:run|tested|verified|done|finished)|left\s+to\s+do|"
    # First person, not a status: "I have not completed the work", "but have not implemented or tested it yet".
    r"(?:(?:have|has|had)\s+(?:not|never)|haven't|hasn't|hadn't)\s+(?:yet\s+)?(?:been\s+)?"
    r"(?:completed?|finished|implemented|tested|committed|verified|started|run|done))\b",
    re.IGNORECASE,
)
# Work the turn leaves behind. Unlike UNFINISHED, "blocked" or "because" beside it does not excuse it.
ABANDONED = re.compile(
    r"\b(?:still\s+outstanding|remain(?:s|ing)?\s+outstanding|"
    r"blocked\s+from\s+(?:completing|finishing)\b[^\n]{0,100}?\b(?:this|the)\s+turn|"
    r"leav(?:e|es|ing)\s+(?:the\s+)?work\b[^\n]{0,80}?\bfor\s+(?:later\s+)?continuation|"
    r"began\b[^\n]{0,160}?\bbut\s+(?:have|has|had)\s+not)\b",
    re.IGNORECASE,
)
NO_ITEMS = re.compile(r"\b(?:no|none|nothing|zero|0)\b", re.IGNORECASE)
NAMED_BLOCKER = re.compile(r"\b(?:block\w*|because|running|until|owner|hold)\b", re.IGNORECASE)
# "because I haven't run them" names no outside blocker.
SELF_CAUSED = re.compile(r"\bbecause\s+(?:i|we)\b", re.IGNORECASE)
STATED_ASK = re.compile(r"^[\s>*-]*NEEDS-OWNER:\s*\S.{7,}", re.IGNORECASE)
OWNER_ONLY_INPUT = re.compile(
    r"\b(?:log\s*in|sign\s*in|password|token|secret|approv\w*|authoriz\w*|force[- ]push|"
    r"delete|send\s+email|protected\s+branch|otp|2fa|verification\s+code|one[- ]time\s+code|"
    r"\d+[- ]digit\s+code|the\s+code\s+(?:sent|texted|emailed)|"
    r"install\s+(?:approval|approve)|approve\s+[^\n]{0,80}\binstall\b|"
    r"(?:install|swap)\s+of\s+bb\b|bb\s+(?:install|swap))\b",
    re.IGNORECASE,
)
QUOTED = re.compile(r"\"[^\"\n]{1,300}\"|“[^”\n]{1,300}”")
IMMEDIATE = re.compile(r"\b(?:now|next|right\s+away|immediately)\b", re.IGNORECASE)
PERMISSION = re.compile(
    r"\b(?:(?:do\s+you\s+)?want\s+me\s+to|would\s+you\s+like\s+me\s+to|(?:should|shall)\s+i|"
    # "If you want it finished, I can ...": up to 6 words between the want and the offer.
    r"if\s+you(?:'d|\s+would)?\s+(?:like|want)(?:\s+[^\s,.;!?]+){0,6}\s*,?\s*i(?:\s+(?:can|could|will)|'ll)|"
    r"your\s+call\s+on|say\s+the\s+word|let\s+me\s+know\s+if\s+you(?:\s+want|'d\s+like|\s+would\s+like)\s+me\s+to)\b",
    re.IGNORECASE,
)
# A wait for the owner's go-ahead on work. It never covers an approval for a delete, install, workflow, merge or
# spend (OWNER_ONLY_INPUT), an owner review, or a real-world action by a person.
WAIT_FOR_OK = re.compile(
    r"\b(?:wait(?:ing)?\s+(?:on|for)|awaiting|pending)\s+(?:your|the\s+owner'?s?|alexandre'?s?)\s+"
    r"(?:go[- ]?ahead|ok(?:ay)?|confirmation|green\s+light|call|decision)\b",
    re.IGNORECASE,
)
# A mention of the owner as the one a wait is for. It is never a stop by itself; a wait on the owner is no
# wait a thread or task can serve, so it is also left out of the dead-wait check.
OWNER_WAIT = re.compile(
    r"\b(?:wait(?:ing)?\s+(?:on|for)|awaiting|pending|need(?:s|ing)?)\s+"
    r"(?:you|your|the\s+owner(?:'s)?|owner(?:'s)?|alexandre(?:'s)?|the\s+user(?:'s)?)\b",
    re.IGNORECASE,
)
# A wait on something the hook can't see: a scheduled automation, a cron, a routine.
SCHEDULED = re.compile(r"\b(?:automations?|cron|crontab|schedul\w*|routines?|timers?)\b", re.IGNORECASE)
# A claim that the work continues somewhere else; it holds only while a child or spawned thread is alive.
HANDOFF = re.compile(
    r"\b(?:continues?\s+in\s+a\s+(?:fresh|new)\s+(?:session|thread)|hand(?:over|off)\s+note|"
    r"hand(?:s|ed|ing)?[- ]?(?:off|over)\s+to\s+a\s+(?:fresh|new)\s+(?:session|thread))\b",
    re.IGNORECASE,
)
# Spend changes the route, never whether owner-requested work gets done.
SPEND = re.compile(
    r"\b(?:weekly[- ](?:limit|usage|quota|budget|cap)|usage[- ]limit|spend(?:ing)?[- ](?:limit|cap|budget|concern)|"
    r"token[- ](?:budget|limit|spend)|quota)",
    re.IGNORECASE,
)
SPEND_STOP = re.compile(
    r"\b(?:stop\w*|paus\w*|hold(?:ing)?|wait\w*|defer\w*|not\s+(?:continu|proceed|start|run)\w*|given|"
    r"because\s+of|due\s+to|out\s+of\s+caution)\b",
    re.IGNORECASE,
)
# A wait the final message claims, as opposed to work the thread does itself.
WAIT_CLAIM = re.compile(
    # Present and future forms only: a done report says "CI finished" or "the watcher reported", not "finishes".
    r"\b(?:wait(?:s|ing)?\s+(?:on|for)|awaiting|(?:i(?:'m|\s+am)|we(?:'re|\s+are)|still|currently)\s+watching|"
    r"watching\s+(?:for|on)|watchers?\s+(?:\S+\s+)?(?:will|is|are|reports|notifies|runs|running)|"
    r"(?:still|currently)\s+(?:running|in\s+progress|pending)|(?:monitor|child|worker)\s+will|"
    r"until\b[^.\n]{0,80}?\b(?:lands?|arrives?|returns?|finish(?:es)?|completes?|comes\s+back)|"
    r"when\b[^.\n]{0,80}?\b(?:returns?|lands?|arrives?|finish(?:es)?|completes?|reports|comes\s+back))\b",
    re.IGNORECASE,
)
CAP = 3
LIVE_CHILD = ("active", "starting", "pending")
CLOSEOUT = os.path.expanduser("~/.agents/skills/scope-ledger/scripts/closeout-stop.py")
STATE_DIR = os.path.expanduser("~/.local/state/agent-quality")
THREAD_ID = re.compile(r"^thr_[a-z0-9]+$")
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def record_native_session(payload):
    """Map this thread to its Claude session and transcript, for the fleet plugin's stopped-thread resumer.

    Written on every Stop-hook run that has a thread id and a session id: exactly {session, transcript_path, ts},
    no message text. Atomic (temp file, then os.replace). Never raises and never touches the hook's decision.
    """
    try:
        thread = os.environ.get("BB_THREAD_ID", "")
        session = payload.get("session_id") or payload.get("sessionId")
        if not THREAD_ID.match(thread) or not isinstance(session, str) or not SESSION_ID.match(session):
            return
        path = payload.get("transcript_path") or payload.get("transcriptPath")
        directory = os.path.join(STATE_DIR, "native-sessions")
        os.makedirs(directory, exist_ok=True)
        target = os.path.join(directory, thread + ".json")
        temp = os.path.join(directory, f".{thread}.{os.getpid()}.tmp")
        try:
            with open(temp, "w", encoding="utf-8") as stream:
                json.dump({"session": session, "transcript_path": path if isinstance(path, str) else None,
                           "ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())}, stream)
            os.replace(temp, target)
        except Exception:
            try:
                os.unlink(temp)
            except OSError:
                pass
    except Exception:
        return


BLOCKED = re.compile(
    r"\b(?:(?:i(?:'m|\s+am)|we(?:'re|\s+are)|am|is|are|still|currently)\s+blocked|blocked\s+(?:on|by)|"
    r"cannot\s+proceed|can(?:'|no)t\s+continue|unable\s+to\s+proceed)\b",
    re.IGNORECASE,
)
NUDGE = (
    "[keep-going] Your last paragraph leaves runnable work open: a promise, a permission question about something "
    "you could just do, or a blocker with no owner-only input.\n"
    "Do the promised or runnable work now with tool calls instead of describing it.\n"
    "Stop when the work is done, or when it waits on an outside event you name and are watching (a run, a review, "
    "a child, a merge). Use `NEEDS-OWNER:` only for a login or code the owner must enter, or one specific approval "
    "a hard prohibition requires; a blocker you can investigate, route around or run yourself is yours."
)
OWNER_ASK_NUDGE = (
    "[keep-going] This NEEDS-OWNER: ask is work you can do. Investigate it, route around it, or run it yourself; "
    "otherwise stop on a named outside event you are watching."
)
MENU = re.compile(
    r"(?:^|\s)\(?[a-d]\)\s|\boption\s+[a-d1-4]\b|\b(?:choose|pick|decide)\b|\bwhich\s+(?:do\s+you|one|option|route|path)\b",
    re.IGNORECASE | re.MULTILINE,
)
MENU_NUDGE = (
    "[keep-going] Your NEEDS-OWNER: hands the owner a menu. If the owner already asked for the outcome and this is "
    "only a route to it, every step is authorized: pick the route yourself, say why in one line, and do it now.\n"
    "If the choice is truly the owner's (a policy, money, an irreversible or outward effect, a login or code, or a "
    "hard prohibition's specific approval), never choose it for them: ask one question with your recommendation, "
    "never a menu."
)


def part_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            str(part.get("text", "")) for part in value
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def assistant_text(entry):
    if not isinstance(entry, dict):
        return ""
    if entry.get("type") == "assistant":
        message = entry.get("message") if isinstance(entry.get("message"), dict) else entry
        return part_text(message.get("content")) or part_text(message.get("text"))
    payload = entry.get("payload")
    if isinstance(payload, dict):
        if payload.get("role") == "assistant" or payload.get("type") in ("agent_message", "assistant_message"):
            return part_text(payload.get("content")) or part_text(payload.get("message")) or part_text(payload.get("text"))
    if entry.get("role") == "assistant":
        return part_text(entry.get("content")) or part_text(entry.get("text"))
    return ""


def transcript_text(path):
    if not isinstance(path, str) or not path:
        return ""
    latest = ""
    try:
        with open(path, encoding="utf-8") as stream:
            for line in stream:
                try:
                    text = assistant_text(json.loads(line))
                except (ValueError, TypeError):
                    continue
                if text:
                    latest = text
    except (OSError, UnicodeError):
        return ""
    return latest


def last_paragraph(text):
    parts = [p for p in re.split(r"\n\s*\n", text.replace("**", "").replace("`", "")) if p.strip()]
    return parts[-1] if parts else ""


def owner_menu(text):
    """A stop line (not a mention of one) whose paragraph offers the owner routes to choose from."""
    text = text.replace("**", "").replace("`", "")
    for match in OWNER_LINE.finditer(text):
        paragraph = re.split(r"\n\s*\n", text[match.start():], maxsplit=1)[0]
        if MENU.search(paragraph):
            return True
    return False


def clean_owner_stop(tail):
    """The tail minus its owner lines, if it closes on a real owner ask; None otherwise.

    A real ask starts its line and makes no promise of its own; a mention of the label does not count.
    """
    asks = [line for line in tail.splitlines() if OWNER_LINE.match(line)]
    if not asks or any(PROMISE.search(line) and not WAITING.search(line) for line in asks):
        return None
    if not any(STATED_ASK.match(line) for line in asks):
        return None
    stated_asks = [line for line in asks if STATED_ASK.match(line)]
    if not any(OWNER_ONLY_INPUT.search(line) for line in stated_asks):
        return None
    return "\n".join(line for line in tail.splitlines() if not OWNER_LINE.match(line))


def open_promise(text):
    """A promise anywhere in the message that no outside wait excuses; a closing paragraph must not hide it.

    A wait excuses only the promise in its own clause, and never one marked as immediate.
    """
    # Quoted text is an example or a citation, not a commitment.
    body = QUOTED.sub("", text.replace("**", "").replace("`", ""))
    return any(PROMISE.search(c) and (IMMEDIATE.search(c) or not excused(c)) for c in CLAUSE.split(body))


def excused(clause):
    """A when/once conditional governs its whole clause; a state wait only the comma part it sits in."""
    if CONDITIONAL.search(clause):
        return True
    return all(STATE_WAIT.search(part) for part in clause.split(",") if PROMISE.search(part))


def sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+|\n", text) if s.strip()]


def runnable_open(text):
    """The class of runnable work a final message leaves open, or None."""
    if open_promise(text):
        return "promise"
    tail = last_paragraph(text)
    # Only a closing owner ask ends the turn; one earlier on must not hide a later promise.
    rest = clean_owner_stop(tail)
    if rest is None and OWNER_LINE.search(tail):
        return "owner-label"  # an owner label with no stated owner-only ask is not a stop
    if rest is not None:
        if not rest.strip():
            return None
        tail = rest
    if PERMISSION.search(tail) or any(WAIT_FOR_OK.search(s) and not OWNER_ONLY_INPUT.search(s) for s in sentences(tail)):
        return "permission"
    # Spend changes the route, never whether owner-requested work gets done.
    if any(SPEND.search(s) and SPEND_STOP.search(s) for s in sentences(tail)):
        return "spend"
    # The turn ends with the work left for later; no outside blocker excuses that.
    if any(ABANDONED.search(c) and not NO_ITEMS.search(c) for c in sentences(tail)):
        return "abandoned"
    # Work stated as not done, with no blocker named beside it, is still runnable.
    if any(UNFINISHED.search(c) and (SELF_CAUSED.search(c) or not (NAMED_BLOCKER.search(c) or WAITING.search(c)))
           for c in CLAUSE.split(tail)):
        return "unfinished"
    return "blocked" if BLOCKED.search(tail) and "?" not in tail else None


_closeout = []


def closeout():
    """closeout-stop.py's module, or None. Imported lazily and inside a try: any failure leaves state unknown."""
    if not _closeout:
        try:
            spec = importlib.util.spec_from_file_location("closeout_stop", CLOSEOUT)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _closeout.append(module)
        except (Exception, SystemExit):
            _closeout.append(None)
    return _closeout[0]


def store_provider(module, thread):
    """The thread's provider_id from bb's store, read-only; None when the store or the row can't be read."""
    try:
        db = module.sqlite3.connect(f"file:{module.BB_DB}?mode=ro", uri=True, timeout=1.0)
        try:
            row = db.execute("SELECT provider_id FROM threads WHERE id = ?", (thread,)).fetchone()
        finally:
            db.close()
        return str(row[0]) if row else None
    except Exception:
        return None


def provider_of(payload):
    """The provider for an event: the store's provider_id, else which native session the transcript belongs to."""
    thread = os.environ.get("BB_THREAD_ID")
    module = closeout() if thread else None
    provider = store_provider(module, thread) if module else None
    if provider:
        return provider
    path = str(payload.get("transcript_path") or payload.get("transcriptPath") or "")
    return "claude-native" if "/.claude/" in path else "codex-native" if "/.codex/" in path else ""


def liveness(payload):
    """What will wake this thread: {"children": bool, "other": bool}, or None when the state can't be read."""
    thread = os.environ.get("BB_THREAD_ID")
    module = closeout() if thread else None
    if module is None:
        return None
    try:
        # A thread id the store doesn't hold reads as "nothing alive"; that is unknown, not a verdict.
        provider = store_provider(module, thread)
        if provider is None:
            return None
        state = module.thread_state(thread)
        children = state.get("children") if isinstance(state, dict) else None
        if children is None:
            return None
        own = state.get("self") if isinstance(state.get("self"), dict) else {}
        live_children = any(c.get("status") in LIVE_CHILD and not c.get("archivedAt") for c in children)
        other = bool(own.get("queuedMessageCount") or own.get("background"))
        transcript = payload.get("transcript_path") or payload.get("transcriptPath")
        if not (live_children or other) and transcript:
            other = bool(module.transcript_background(transcript))
        # Only Claude Code threads record their background tasks in the store (Codex, Cursor and OpenCode record
        # none), so for any other provider a task that isn't there proves nothing.
        return {"children": live_children, "other": other, "sees_tasks": provider.startswith("claude-code")}
    except Exception:
        return None


def claim_class(text, payload):
    """A wait or handoff the final message claims that nothing alive carries, or None.

    Only the last paragraph counts, less any real owner ask: a done report that mentions a past watcher earlier
    on must pass. An unknown state never blocks.
    """
    tail = last_paragraph(text)
    rest = clean_owner_stop(tail)
    # A wait on the owner is judged by the phrasing checks (OWNER_WAIT): no thread or task can serve it.
    body = " ".join(s for s in sentences(QUOTED.sub("", rest if rest is not None else tail))
                    if not OWNER_WAIT.search(s))
    # The hook can't see a scheduled automation or cron, so a wait on one falls back to the phrasing checks.
    waits = WAIT_CLAIM.search(" ".join(s for s in sentences(body) if not SCHEDULED.search(s)))
    handoff = HANDOFF.search(body)
    if not (waits or handoff):
        return None
    alive = liveness(payload)
    if alive is None:
        return None
    if handoff and not alive["children"]:
        return "handoff"
    if waits and alive["sees_tasks"] and not (alive["children"] or alive["other"]):
        return "unserved-wait"
    return None


def classify(text, payload):
    """Why this final message must not end the turn: a class name, or None."""
    if owner_menu(text):
        return "owner-menu"
    para = last_paragraph(text)
    if re.search(r"^[\s>*-]*NEEDS-OWNER:\s*\S.{7,}", para, re.IGNORECASE | re.MULTILINE) and clean_owner_stop(para) is None:
        return "owner-ask"
    return claim_class(text, payload) or runnable_open(text)


def turn_key(payload):
    """Timestamp of the transcript's last real user prompt, which marks the turn; None when unreadable."""
    path = payload.get("transcript_path") or payload.get("transcriptPath")
    module = closeout() if path else None
    try:
        return module.last_human_input_at(path) if module else None
    except Exception:
        return None


def may_block(payload, cls):
    """True to block this stop. Up to CAP blocks per turn; after that the stop goes through and one event is kept."""
    active = bool(payload.get("stop_hook_active") or payload.get("stopHookActive"))
    session = payload.get("session_id") or payload.get("sessionId")
    if not isinstance(session, str) or not session:
        return not active  # no counter without a session: keep the one-shot behaviour
    try:
        path = os.path.join(STATE_DIR, "keepgoing", re.sub(r"[^A-Za-z0-9_.-]", "_", session) + ".json")
        key = turn_key(payload)
        try:
            with open(path, encoding="utf-8") as stream:
                data = json.load(stream)
            data = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            data = {}
        # A hook retry is always the same turn, whatever the transcript shows. Otherwise a new user prompt starts
        # a turn; with no readable prompt, any stop outside a retry does.
        same = active or (key is not None and data.get("turn") == key)
        count = int(data.get("count", 0)) if same else 0
        capped = bool(data.get("capped")) if same else False
        # The turn's start: the user prompt's own timestamp, else the time of its first block.
        started = (data.get("started") if same else None) or key or time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if count >= CAP:
            if not capped:
                event = {"schema_version": 1, "ts": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
                         "event": "keepgoing-cap-reached", "thread": os.environ.get("BB_THREAD_ID", ""),
                         "session": session, "class": cls, "turn_started_at": started,
                         "provider": provider_of(payload)}
                with open(os.path.join(STATE_DIR, "events.jsonl"), "a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event) + "\n")
                with open(path, "w", encoding="utf-8") as stream:
                    json.dump({"turn": key, "count": count, "capped": True, "started": started}, stream)
            return False
        with open(path, "w", encoding="utf-8") as stream:
            json.dump({"turn": key, "count": count + 1, "started": started}, stream)
        return True
    except Exception:
        return not active


REASONS = {
    "owner-menu": MENU_NUDGE,
    "owner-ask": OWNER_ASK_NUDGE,
    "unserved-wait": (
        "[keep-going] You say you are waiting, but nothing is running that will wake you: no background task, "
        "no active child, no queued message. Start the watcher, check the child, or do the work now."
    ),
    "handoff": (
        "[keep-going] You claim the work continues in another session, but no child or spawned thread is alive. "
        "Start that thread now, or do the work yourself."
    ),
    "spend": (
        "[keep-going] A weekly limit or spend concern changes the route, never whether work the owner asked for "
        "gets done. Pick a cheaper route and finish it."
    ),
}


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        record_native_session(payload)
        text = payload.get("last_assistant_message") or payload.get("lastAssistantMessage") or payload.get("text")
        if not isinstance(text, str) or not text:
            text = transcript_text(payload.get("transcript_path") or payload.get("transcriptPath"))
        cls = classify(text, payload) if text else None
        if cls and may_block(payload, cls):
            print(json.dumps({"decision": "block", "reason": REASONS.get(cls, NUDGE)}))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
