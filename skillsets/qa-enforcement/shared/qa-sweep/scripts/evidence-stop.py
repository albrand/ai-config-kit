#!/usr/bin/env python3
"""One-turn nudge when a final message makes an unsupported completion claim."""
import json
import os
import re
import sys


CLAIM_PATTERNS = (
    re.compile(
        r"\b(?:i|we)\s+(?:(?:have|has)\s+)?(?:now\s+|just\s+)?"
        r"(?P<claim>done|complete(?:d)?|finished|shipped|deployed|ready|fixed|resolved|implemented|works?\b|working|tested|verified|validated)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:it|this|everything|all|the\s+(?:requested\s+)?(?:work|task|change|fix|feature|workflow|flow|issue|bug|request|implementation|build|app|site|release|pr|deployment|branch|journey))\s+"
        r"(?:is|are|was|were|has been|have been|is now|are now|was now|were now)\s+"
        r"(?P<claim>done|complete(?:d)?|finished|shipped|deployed|ready|fixed|resolved|implemented|works?\b|working|tested|verified|validated)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:#{1,6}\s*)?(?:\*\*)?(?P<claim>done|complete(?:d)?|finished|shipped|deployed|ready|fixed|resolved|implemented|tested|verified|validated)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
)
NEGATED = re.compile(
    r"\b(?:not|never|cannot|can't|isn't|aren't|wasn't|weren't|didn't|"
    r"haven't|hasn't|won't|will not|not yet|unable to)\b",
    re.IGNORECASE,
)
NOT_RUN = re.compile(r"\bimplemented\s*[;—-]\s*workflow\s+not\s+run\b", re.IGNORECASE)
REMAINS = re.compile(r"\b(?:what remains|remaining|still needs? to|next steps?|remains? to)\b", re.IGNORECASE)


def has_evidence_packet(text):
    labels = (
        re.search(r"\bpersona\s*:", text, re.IGNORECASE),
        re.search(r"\btarget\s*:", text, re.IGNORECASE),
        re.search(r"\bgoals? attempted\s*:", text, re.IGNORECASE),
        re.search(r"\bverdicts?\s*:", text, re.IGNORECASE),
    )
    if not all(labels):
        return False
    target = text[labels[1].end(): labels[2].start()]
    has_deployment = bool(re.search(r"https?://\S+", target) and re.search(r"\bdeployment(?:\s+id)?\b", target, re.IGNORECASE))
    has_stack_sha = bool(
        re.search(r"\b(?:stack|repo|project)\b", target, re.IGNORECASE)
        and re.search(r"\b(?:commit|sha)\b", target, re.IGNORECASE)
        and re.search(r"\b[0-9a-f]{7,40}\b", target, re.IGNORECASE)
    )
    return has_deployment or has_stack_sha


def first_claim(text):
    found = []
    for pattern in CLAIM_PATTERNS:
        found.extend(pattern.finditer(text))
    for match in sorted(found, key=lambda item: item.start()):
        prefix = text[max(0, match.start() - 36):match.start()]
        line = text[text.rfind("\n", 0, match.start()) + 1:match.start()]
        if line.lstrip().startswith(">") or NEGATED.search(prefix):
            continue
        return match.group("claim").lower()
    return None


def inspect(text):
    claim = first_claim(text)
    if claim is None or has_evidence_packet(text):
        return {"block": False, "claim": claim}
    not_run = NOT_RUN.search(text)
    if not_run and REMAINS.search(text[not_run.end():]):
        return {"block": False, "claim": claim, "not_run": True}
    reason = (
        "[qa-evidence] Final message contains a completion or test claim without an evidence packet. "
        "Attach a packet with persona, target (stack plus commit SHA or deployment ID), user outcomes "
        "attempted, and a verdict for each goal; or restate the claim as ‘implemented; workflow NOT RUN’ "
        "and say what remains. This is a one-time nudge for this turn."
    )
    return {"block": True, "claim": claim, "reason": reason}


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
    """Extract assistant text from Claude JSONL or Codex rollout entries."""
    if not isinstance(entry, dict):
        return ""
    if entry.get("type") == "assistant":
        message = entry.get("message") if isinstance(entry.get("message"), dict) else entry
        return part_text(message.get("content")) or part_text(message.get("text"))
    payload = entry.get("payload")
    if isinstance(payload, dict):
        if payload.get("role") == "assistant" or payload.get("type") in ("agent_message", "assistant_message"):
            return part_text(payload.get("content")) or part_text(payload.get("message")) or part_text(payload.get("text"))
        if payload.get("type") == "message" and payload.get("role") == "assistant":
            return part_text(payload.get("content")) or part_text(payload.get("text"))
    if entry.get("role") == "assistant":
        return part_text(entry.get("content")) or part_text(entry.get("text"))
    return ""


def transcript_assistant_text(path):
    if not isinstance(path, str) or not path:
        return ""
    try:
        latest = ""
        with open(path, encoding="utf-8") as stream:
            for line in stream:
                try:
                    text = assistant_text(json.loads(line))
                except (json.JSONDecodeError, TypeError):
                    continue
                if text:
                    latest = text
        return latest
    except (OSError, UnicodeError):
        return ""


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    if payload.get("stop_hook_active") or payload.get("stopHookActive"):
        return 0
    text = payload.get("text")
    if not isinstance(text, str):
        text = payload.get("last_assistant_message") or payload.get("lastAssistantMessage") or ""
    if not isinstance(text, str) or not text:
        text = transcript_assistant_text(payload.get("transcript_path") or payload.get("transcriptPath"))
    if not isinstance(text, str) or not text:
        return 0
    result = inspect(text)
    if result["block"]:
        print(json.dumps({"decision": "block", "reason": result["reason"]}))
    else:
        print(json.dumps({"decision": "allow", "claim": result.get("claim"), "not_run": result.get("not_run", False)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
