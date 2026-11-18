#!/usr/bin/env python3
"""PreToolUse Bash guard for invalid bb thread statuses and tight wait loops."""
import json
import re
import sys


STATUSES = {"pending", "idle", "starting", "active", "stopping", "error"}
SUGGESTION = "Use one `bb thread wait <thr> --status active --timeout 1h --poll-interval 120000` call; do not retry it in a loop."


def command_from(payload):
    if not isinstance(payload, dict):
        return None
    name = payload.get("tool_name", payload.get("toolName", ""))
    if not isinstance(name, str) or not name.lower().endswith("bash"):
        return None
    data = payload.get("tool_input", payload.get("toolInput", payload.get("input", {})))
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        return None
    command = data.get("command", data.get("cmd"))
    return command if isinstance(command, str) else None


def reason(command):
    # Status is checked without invoking bb; hook execution must remain local and fast.
    for match in re.finditer(r"\bbb\s+thread\s+wait\b([^;&|\n]*)", command):
        args = match.group(1)
        status = re.search(r"(?:^|\s)--status(?:=|\s+)([^\s]+)", args)
        if status and status.group(1).strip("'\"\\") not in STATUSES:
            return f"Invalid bb thread status {status.group(1)!r}. Valid statuses are pending, idle, starting, active, stopping, error. {SUGGESTION}"

    # Identify shell loop bodies. A wait/show loop is safe only when its body
    # contains an explicit sleep or a bb polling interval.
    loops = re.finditer(r"\b(?:until|while)\b(.*?)(?:\bdo\b)(.*?)(?:\bdone\b)", command, re.I | re.S)
    for loop in loops:
        body = loop.group(2)
        if re.search(r"\bbb\s+thread\s+(?:wait|show)\b", body):
            if not re.search(r"\bsleep\b|--poll-interval(?:=|\s)", body):
                return f"This bb thread wait/show loop has no delay and can spin at full CPU. {SUGGESTION}"
    return None


def main():
    try:
        payload = json.load(sys.stdin)
        command = command_from(payload)
        message = reason(command) if command is not None else None
    except (ValueError, TypeError, KeyError):
        message = None
    if message:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": message}}))
        print(message, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
