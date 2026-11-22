#!/usr/bin/env python3
"""Temporary live probe: deny one harmless command marker, otherwise no-op."""
import json
import sys

MARKER = "SECRETS-GUARD-PRECEDENCE-PROBE"


def main():
    try:
        event = json.load(sys.stdin)
        tool_input = event.get("tool_input", {})
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if not isinstance(command, str):
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "Probe hook failed closed: missing command"}}))
            return 0
        if MARKER in command:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "SECRETS-GUARD-PRECEDENCE-PROBE denied by independent test hook"}}))
        else:
            print("{}")
        return 0
    except Exception:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "Probe hook failed closed"}}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
