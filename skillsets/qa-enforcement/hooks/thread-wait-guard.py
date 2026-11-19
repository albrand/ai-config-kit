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


def shell_tokens(command):
    """Return shell words/operators, ignoring quoted text and comments as syntax."""
    tokens = []
    i = 0
    operators = ";&|()\n"
    while i < len(command):
        if command[i].isspace():
            i += 1
            continue
        if command[i] == "#":
            newline = command.find("\n", i)
            i = len(command) if newline < 0 else newline + 1
            continue
        if command[i] in operators:
            tokens.append((command[i], i, i + 1, True))
            i += 1
            continue

        start = i
        pieces = []
        bare = True
        while i < len(command) and not command[i].isspace() and command[i] not in operators:
            char = command[i]
            if char in "'\"":
                bare = False
                quote = char
                i += 1
                while i < len(command) and command[i] != quote:
                    if quote == '"' and command[i] == "\\" and i + 1 < len(command):
                        i += 1
                    pieces.append(command[i])
                    i += 1
                if i < len(command):
                    i += 1
            elif char == "\\" and i + 1 < len(command):
                bare = False
                i += 1
                pieces.append(command[i])
                i += 1
            else:
                pieces.append(char)
                i += 1
        tokens.append(("".join(pieces), start, i, bare))
    return tokens


def reason(command):
    # Status is checked without invoking bb; hook execution must remain local and fast.
    for match in re.finditer(r"\bbb\s+thread\s+wait\b([^;&|\n]*)", command):
        args = match.group(1)
        status = re.search(r"(?:^|\s)--status(?:=|\s+)([^\s]+)", args)
        if status and status.group(1).strip("'\"\\") not in STATUSES:
            return f"Invalid bb thread status {status.group(1)!r}. Valid statuses are pending, idle, starting, active, stopping, error. {SUGGESTION}"

    # A wait/show can run in either the loop condition or body. It is safe
    # only when the loop body sleeps or the wait has an explicit poll interval.
    loops = []
    stack = []
    tokens = shell_tokens(command)
    for word, token_start, token_end, bare in tokens:
        word = word.lower()
        if not bare:
            continue
        if word in {"until", "while"}:
            stack.append({"start": token_start, "do": None})
        elif word == "do":
            pending = next((loop for loop in reversed(stack) if loop["do"] is None), None)
            if pending is not None:
                pending["do"] = token_end
        elif word == "done" and stack:
            loop = stack.pop()
            if loop["do"] is not None:
                loops.append((loop["start"], loop["do"], token_start, token_end))

    for start, body_start, body_end, end in loops:
        whole_loop = command[start:end]
        body = command[body_start:body_end]
        words = [word for word, _, _, _ in shell_tokens(whole_loop)]
        has_wait = any(words[index:index + 3] in (["bb", "thread", "wait"], ["bb", "thread", "show"]) for index in range(len(words) - 2))
        has_sleep = any(word == "sleep" for word, _, _, _ in shell_tokens(body))
        has_poll_interval = any(word == "--poll-interval" or word.startswith("--poll-interval=") for word in words)
        if has_wait:
            if not has_sleep and not has_poll_interval:
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
