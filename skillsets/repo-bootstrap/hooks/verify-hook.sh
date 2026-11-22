#!/bin/sh
# PostToolUse (Claude Code and Codex, same schema): after a merge, deploy or protected push, add the
# commit's verify result to the agent's context. Never denies; any failure is silent.
V="$HOME/.agents/skills/verify/scripts/verify.py"
[ -f "$V" ] || exit 0
exec python3 "$V" hook 2>/dev/null
