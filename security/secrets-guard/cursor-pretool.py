#!/usr/bin/env python3
"""Fail-closed Cursor beforeShellExecution adapter for local and ACP agents."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guard import denied


def result(permission, message):
    return {
        "permission": permission,
        "user_message": message,
        "agent_message": message,
    }


def main():
    try:
        event = json.load(sys.stdin)
        command = event.get("command")
        if not isinstance(command, str):
            tool_input = event.get("tool_input", {})
            command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if not isinstance(command, str):
            raise ValueError("missing command")
        if denied(command):
            response = result(
                "deny",
                "Secret-value output blocked. Use secret-names <file> to inspect variable names with values masked.",
            )
        else:
            # Keep Cursor's normal permission decision for non-matching commands.
            response = result("ask", "Secret guard found no deny rule; confirm under normal policy.")
    except Exception:
        response = result("deny", "Secret guard failed closed; command not run.")
    print(json.dumps(response))
    return 0


if __name__ == "__main__":
    sys.exit(main())
