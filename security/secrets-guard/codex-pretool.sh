#!/bin/sh
set -eu
payload=$(cat) || payload='{}'
result=$(printf '%s' "$payload" | /usr/bin/python3 "$HOME/.agent-hooks/secrets-guard.py") || result='{"block":true,"reason":"Secret guard failed closed; command not run."}'
if out=$(printf '%s' "$result" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":d.get("reason","Secret guard failed closed.")}})) if d.get("block") else print("{}"); print(d.get("reason","Secret guard failed closed."),file=sys.stderr) if d.get("block") else None; sys.exit(2 if d.get("block") else 0)'); then
  printf '%s\n' "$out"
else
  printf '%s\n' "Secret guard failed closed; command not run." >&2
  printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Secret guard adapter failed closed."}}'
  exit 2
fi
