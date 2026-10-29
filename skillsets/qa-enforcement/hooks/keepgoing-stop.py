#!/usr/bin/env python3
"""One-turn nudge when a final message stops with runnable work still open."""
import json
import re
import sys


OWNER_LINE = re.compile(r"^[\s>*-]*(?:NEEDS-OWNER:|STATUS:\s*needs-owner)", re.IGNORECASE | re.MULTILINE)
PROMISE = re.compile(
    r"\b(?:i(?:'ll|\s+will|'m\s+going\s+to|\s+am\s+going\s+to)|we(?:'ll|\s+will)|next,?\s+i\s+will|next\s+up|"
    r"let\s+me\s+(?!know\b)[a-z]+|let\s+me\s+know\s+(?:when|once|as\s+soon\s+as))\b",
    re.IGNORECASE,
)
# A conditional counts only when it names an outside event finishing or arriving, not more of our own work.
CONDITIONAL = re.compile(
    r"\b(?:when|once|as\s+soon\s+as|after)\s+(?!(?:i|we)\b|i'|we')[^.;!?]{0,60}?\b(?:(?:arriv|finish|land|comes?\s+back|"
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
    r"needs?\s+to\s+be\s+(?:run|tested|verified|done|finished)|left\s+to\s+do)\b",
    re.IGNORECASE,
)
NAMED_BLOCKER = re.compile(r"\b(?:block\w*|because|running|until|owner|hold)\b", re.IGNORECASE)
# "because I haven't run them" names no outside blocker.
SELF_CAUSED = re.compile(r"\bbecause\s+(?:i|we)\b", re.IGNORECASE)
STATED_ASK = re.compile(r"^[\s>*-]*NEEDS-OWNER:\s*\S.{7,}", re.IGNORECASE)
QUOTED = re.compile(r"\"[^\"\n]{1,300}\"|“[^”\n]{1,300}”")
IMMEDIATE = re.compile(r"\b(?:now|next|right\s+away|immediately)\b", re.IGNORECASE)
PERMISSION = re.compile(
    r"\b(?:(?:do\s+you\s+)?want\s+me\s+to|would\s+you\s+like\s+me\s+to|(?:should|shall)\s+i|"
    r"if\s+you(?:'d|\s+would)?\s+(?:like|want),?\s+i\s+(?:can|could|will|'ll))\b",
    re.IGNORECASE,
)
BLOCKED = re.compile(
    r"\b(?:(?:i(?:'m|\s+am)|we(?:'re|\s+are)|am|is|are|still|currently)\s+blocked|blocked\s+(?:on|by)|"
    r"cannot\s+proceed|can(?:'|no)t\s+continue|unable\s+to\s+proceed)\b",
    re.IGNORECASE,
)
NUDGE = (
    "[keep-going] Your last paragraph leaves runnable work open: a promise, a permission question about something "
    "you could just do, or a blocker with no owner-only input.\n"
    "Do the promised or runnable work now with tool calls instead of describing it.\n"
    "Stop only with a line `NEEDS-OWNER: <the login, code or approval only the owner can give>`."
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


def runnable_open(text):
    if open_promise(text):
        return True
    tail = last_paragraph(text)
    # Only a closing owner ask ends the turn; one earlier on must not hide a later promise.
    rest = clean_owner_stop(tail)
    if rest is None and OWNER_LINE.search(tail):
        return True  # an owner label with no stated owner-only ask is not a stop
    if rest is not None:
        if not rest.strip():
            return False
        tail = rest
    if PERMISSION.search(tail):
        return True
    # Work stated as not done, with no blocker named beside it, is still runnable.
    if any(UNFINISHED.search(c) and (SELF_CAUSED.search(c) or not (NAMED_BLOCKER.search(c) or WAITING.search(c)))
           for c in CLAUSE.split(tail)):
        return True
    return bool(BLOCKED.search(tail)) and "?" not in tail


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or payload.get("stop_hook_active") or payload.get("stopHookActive"):
            return 0
        text = payload.get("last_assistant_message") or payload.get("lastAssistantMessage") or payload.get("text")
        if not isinstance(text, str) or not text:
            text = transcript_text(payload.get("transcript_path") or payload.get("transcriptPath"))
        if text and owner_menu(text):
            print(json.dumps({"decision": "block", "reason": MENU_NUDGE}))
        elif text and runnable_open(text):
            print(json.dumps({"decision": "block", "reason": NUDGE}))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
