#!/bin/sh
set -eu
payload=$(cat)
result=$(printf '%s' "$payload" | /usr/bin/python3 "$HOME/.agent-hooks/secrets-guard.py") || result='{"block":true,"reason":"Secret guard failed closed; command not run."}'
printf '%s' "$result" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0) if not d.get("block") else print(json.dumps({"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":d.get("reason","Secret guard failed closed.")}}))'
