#!/bin/sh
# Claude Code + Codex adapter for coordinator-mode.py.
#   coordinator-hook.sh prompt   (UserPromptSubmit) -> additionalContext
#   coordinator-hook.sh pretool  (PreToolUse)       -> deny JSON + stderr + exit 2
# Emits Claude-style hookSpecificOutput, which Codex also reads; the exit-2 +
# stderr form blocks under either convention. Fails open on any error.
kind=${1:-pretool}
v=$(python3 "$HOME/.agent-hooks/coordinator-mode.py" "$kind" 2>/dev/null) || exit 0
printf '%s' "$v" | KIND="$kind" python3 -c '
import sys, json, os
try: d = json.load(sys.stdin)
except Exception: sys.exit(0)
kind = os.environ.get("KIND")
if kind == "prompt" and d.get("context"):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                             "additionalContext": d["context"]}}))
    sys.exit(0)
if kind == "pretool" and d.get("block"):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
        "permissionDecision": "deny", "permissionDecisionReason": d.get("reason", "")}}))
    sys.stderr.write(d.get("reason", "") + "\n")
    sys.exit(2)
'
rc=$?
[ "$rc" = 2 ] && exit 2
exit 0
