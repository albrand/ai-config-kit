#!/usr/bin/env python3
"""One-turn nudge when a final message stops with runnable work still open."""
import json
import re
import sys


OWNER = re.compile(r"NEEDS-OWNER:|STATUS:\s*needs-owner", re.IGNORECASE)
PROMISE = re.compile(
    r"\b(?:i(?:'ll|\s+will|'m\s+going\s+to|\s+am\s+going\s+to)|we(?:'ll|\s+will)|next,?\s+i\s+will|next\s+up|"
    r"let\s+me\s+(?!know\b)[a-z]+|let\s+me\s+know\s+(?:when|once|as\s+soon\s+as))\b",
    re.IGNORECASE,
)
WAITING = re.compile(
    r"\b(?:still\s+(?:running|in\s+progress|pending)|in\s+progress|waiting\s+(?:on|for)|watch(?:ing|er)|notif\w*|"
    r"(?:when|once|as\s+soon\s+as|after)\s+[\w'-]+|"
    r"(?:monitor|child|worker)\s+will)\b",
    re.IGNORECASE,
)
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
    "[keep-going] Your NEEDS-OWNER: hands the owner a choice of routes. The owner already asked for the outcome, "
    "so every step needed to reach it is authorized: pick the route yourself, say why in one line, and do it now.\n"
    "Keep NEEDS-OWNER only for input the owner has not given and only they can give: a login or code, or a hard "
    "prohibition's specific approval. Then ask for that one thing, with your recommendation, never a menu."
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


OWNER_LINE = re.compile(r"^[\s>*-]*(?:NEEDS-OWNER:|STATUS:\s*needs-owner)", re.IGNORECASE | re.MULTILINE)


def owner_menu(text):
    """A stop line (not a mention of one) whose paragraph offers the owner routes to choose from."""
    text = text.replace("**", "").replace("`", "")
    for match in OWNER_LINE.finditer(text):
        paragraph = re.split(r"\n\s*\n", text[match.start():], maxsplit=1)[0]
        if MENU.search(paragraph):
            return True
    return False


def runnable_open(text):
    tail = last_paragraph(text)
    # Only a closing owner ask ends the turn; one earlier on must not hide a later promise.
    if OWNER.search(tail):
        return False
    if PERMISSION.search(tail):
        return True
    if PROMISE.search(tail) and not WAITING.search(tail):
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
