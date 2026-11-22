#!/bin/sh
set -eu
payload=$(cat)
result=$(printf '%s' "$payload" | /usr/bin/python3 "$HOME/.agent-hooks/secrets-guard.py") || result='{"block":true,"reason":"Secret guard failed closed; command not run."}'
reason=$(printf '%s' "$result" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("reason", "Secret guard failed closed.")) if d.get("block") else None')
[ -z "$reason" ] && exit 0
printf '%s\n' "$reason" >&2
printf '%s' "$result" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":d.get("reason","Secret guard failed closed.")}}))'
exit 2
