#!/bin/sh
set -eu
payload=$(cat) || payload='{}'
result=$(printf '%s' "$payload" | /usr/bin/python3 "$HOME/.agent-hooks/secrets-guard.py") || result='{"block":true,"reason":"Secret guard failed closed; command not run."}'
out=$(printf '%s' "$result" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); o={"hookEventName":"PreToolUse"}; o.update({"permissionDecision":"deny","permissionDecisionReason":d.get("reason","Secret guard failed closed.")} if d.get("block") else {"permissionDecision":"allow","updatedInput":{"command":d["updated_command"]}}); print(json.dumps({"hookSpecificOutput":o}))') || out='{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Secret guard adapter failed closed."}}'
printf '%s\n' "$out"
