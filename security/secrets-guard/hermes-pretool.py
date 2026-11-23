#!/usr/bin/env python3
"""Fail-closed Hermes pre_tool_call adapter for command and file-read tools.

Hermes shell hooks can block a tool call but cannot rewrite its arguments, so
this adapter is deny-only. It covers every Hermes route that can put a secret
value into the model's context: shell commands (terminal, and text written to a
running process), direct file reads, content search, and execute_code.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard

READ_TOOLS = {"read_file", "read_document", "open_file"}
PROCESS_INPUT_ACTIONS = {"write", "submit"}
# execute_code runs Python. Do not shlex-parse it through guard.denied():
# ordinary Python quoting would raise and block every call.
CODE_READ = re.compile(r"\b(?:open|read|read_text|read_bytes|readFile|readFileSync|createReadStream|load_dotenv|dotenv_values|subprocess|system|popen|check_output|run)\b")
CODE_ENV = re.compile(r"(?i)(?:os\.environ|os\.getenv|getenv\s*\(|process\.env)")
CODE_OUTPUT = re.compile(r"(?i)(?:print|pprint|echo|printf|console\.log|write\s*\(|json\.dumps|repr\s*\(|str\s*\()")
CODE_ENV_DUMP = re.compile(r"(?:os\.environ\s*\)|os\.environ\s*$|os\.environ\.(?:items|values|copy)\s*\(|dict\s*\(\s*os\.environ|\{\s*\*\*\s*os\.environ)", re.M)

COMMAND_REASON = "Secret-value output blocked. Use secret-names <file> to inspect variable names with values masked."
FILE_REASON = "Reading credential files into agent context is blocked. Use secret-names <file> for names only."
CODE_REASON = "Secret-value output from execute_code blocked. Use secret-names <file> for names only."


def blocked(reason):
    return {"decision": "block", "reason": reason}


def code_denied(code):
    if guard.URI.search(code):
        return True
    if guard.FILES.search(code) and CODE_READ.search(code):
        return True
    if CODE_ENV.search(code) and CODE_OUTPUT.search(code):
        if guard.SENSITIVE.search(code) or CODE_ENV_DUMP.search(code):
            return True
    return False


def decide(tool, args):
    command = args.get("command")
    if isinstance(command, str) and guard.denied(command):
        return blocked(COMMAND_REASON)

    if tool == "process" and str(args.get("action") or "").lower() in PROCESS_INPUT_ACTIONS:
        data = args.get("data")
        if isinstance(data, str) and guard.denied(data):
            return blocked(COMMAND_REASON)

    if tool in READ_TOOLS:
        path = args.get("path") or args.get("file_path")
        if isinstance(path, str) and guard.FILES.search(path):
            return blocked(FILE_REASON)

    if tool == "search_files" and str(args.get("target") or "content").lower() != "files":
        for key in ("path", "file_glob"):
            value = args.get(key)
            if isinstance(value, str) and guard.FILES.search(value):
                return blocked(FILE_REASON)

    if tool == "execute_code":
        code = args.get("code")
        if isinstance(code, str) and code_denied(code):
            return blocked(CODE_REASON)

    return {}


def main():
    try:
        event = json.load(sys.stdin)
        tool = str(event.get("tool_name") or "").lower()
        args = event.get("tool_input") or {}
        if not isinstance(args, dict):
            raise ValueError("tool_input must be an object")
        print(json.dumps(decide(tool, args)))
        return 0
    except Exception:
        print(json.dumps(blocked("Secret guard failed closed; tool call not run.")))
        return 0


if __name__ == "__main__":
    sys.exit(main())
