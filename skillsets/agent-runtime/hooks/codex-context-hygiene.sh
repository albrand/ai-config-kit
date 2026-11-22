#!/bin/sh
# Codex PreToolUse adapter -> shared policy (~/.agent-hooks/context-hygiene-policy.py,
# source: ai-config-kit skillsets/agent-runtime/hooks). Emits Claude-style deny JSON AND
# exits 2 with stderr, so it blocks under either convention. Fails open.
payload=$(cat)
v=$(printf '%s' "$payload" | python3 "$HOME/.agent-hooks/context-hygiene-policy.py" 2>/dev/null) || exit 0
reason=$(printf '%s' "$v" | python3 -c 'import sys,json
try: d=json.load(sys.stdin)
except Exception: sys.exit(0)
sys.stdout.write(d.get("reason","") if d.get("block") else "")' 2>/dev/null) || exit 0
[ -z "$reason" ] && exit 0
printf '%s\n' "$v" | python3 -c 'import sys,json
d=json.load(sys.stdin)
print(json.dumps({"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":d.get("reason","")}}))' 2>/dev/null
printf '%s\n' "$reason" >&2
exit 2
