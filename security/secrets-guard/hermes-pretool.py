#!/usr/bin/env python3
"""Fail-closed Hermes pre_tool_call adapter for command and file-read tools."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard

READ_TOOLS = {"read_file", "read_document", "open_file"}


def blocked(reason):
    return {"decision": "block", "reason": reason}


def main():
    try:
        event = json.load(sys.stdin)
        tool = str(event.get("tool_name") or "").lower()
        args = event.get("tool_input") or {}
        if not isinstance(args, dict):
            raise ValueError("tool_input must be an object")

        command = args.get("command")
        if isinstance(command, str) and guard.denied(command):
            print(json.dumps(blocked("Secret-value output blocked. Use names-only inspection with values masked.")))
            return 0

        if tool in READ_TOOLS:
            path = args.get("path") or args.get("file_path")
            if isinstance(path, str) and guard.FILES.search(path):
                print(json.dumps(blocked("Reading credential files into agent context is blocked.")))
                return 0

        print("{}")
        return 0
    except Exception:
        print(json.dumps(blocked("Secret guard failed closed; tool call not run.")))
        return 0


if __name__ == "__main__":
    sys.exit(main())
