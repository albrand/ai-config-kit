#!/bin/sh
# Claude Code PreToolUse adapter -> shared policy at ~/.agent-hooks/
# Blocks with permissionDecision:deny; fails open on any error.
payload=$(cat)
v=$(printf '%s' "$payload" | python3 "$HOME/.agent-hooks/context-hygiene-policy.py" 2>/dev/null) || exit 0
printf '%s' "$v" | python3 -c '
import sys, json
try: d = json.load(sys.stdin)
except Exception: sys.exit(0)
if not d.get("block"): sys.exit(0)
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": d.get("reason","")}}))
' 2>/dev/null || exit 0
exit 0
