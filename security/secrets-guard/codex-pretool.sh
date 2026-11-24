#!/bin/sh
set -eu
payload=$(cat) || payload='{}'
result=$(printf '%s' "$payload" | /usr/bin/python3 "$HOME/.agent-hooks/secrets-guard.py") || result='{"block":true,"reason":"Secret guard failed closed; command not run."}'
# The converter prints the hook JSON and, on a block, the guard's own reason; it exits 0 either way.
# The exit status is decided here, so a genuine block is not mistaken for an adapter failure.
if out=$(printf '%s' "$result" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); b=bool(d.get("block")); o={"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":d.get("reason","Secret guard failed closed.")} if b else {"hookEventName":"PreToolUse","permissionDecision":"allow","updatedInput":{"command":d["updated_command"]}}; print(json.dumps({"hookSpecificOutput":o})); print("BLOCK" if b else "ALLOW",file=sys.stderr)' 2>/dev/null); then
  :
else
  out=''
fi
if [ -z "$out" ]; then
  printf '%s\n' "Secret guard failed closed; command not run." >&2
  printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Secret guard adapter failed closed."}}'
  exit 2
fi
printf '%s\n' "$out"
case "$out" in
  *'"permissionDecision": "deny"'*)
    reason=$(printf '%s' "$out" | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)["hookSpecificOutput"]["permissionDecisionReason"])' 2>/dev/null) || reason='Secret guard blocked the command.'
    printf '%s\n' "$reason" >&2
    exit 2 ;;
esac
