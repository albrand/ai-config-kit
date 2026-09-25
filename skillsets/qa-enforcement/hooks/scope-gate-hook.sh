#!/bin/sh
# PreToolUse adapter for the scope gate (Claude Code + Codex via
# coordinator-hook-pretool.sh). Reads the hook payload on stdin.
#   exit 0 + no output = allow; exit 2 + JSON/stderr = deny.
# Only a thread with a scope ledger is ever gated: everything else leaves at
# the first test, before python starts. For a ledger thread, a dispatch
# (bb thread spawn|create|tell|message, fleet_member_spawn|tell,
# fleet_delegate) must carry `serves: P<n>` for an open purpose or
# `serves: revision "<quote>"` for an accepted revision.
DIR="${SCOPE_LEDGER_DIR:-$HOME/.local/state/agent-quality/scope}"
GATE="$HOME/.agents/skills/scope-ledger/scripts/scope-gate.py"
[ -n "${BB_THREAD_ID:-}" ] && [ -f "$DIR/$BB_THREAD_ID.json" ] || exit 0
input=$(cat)
# Cheap prefilter: no dispatch shape anywhere in the payload, nothing to gate.
printf '%s' "$input" | grep -qE 'fleet_member_|fleet_delegate|thread' || exit 0
set +e
if [ -f "$GATE" ] && command -v python3 >/dev/null 2>&1; then
  printf '%s' "$input" | python3 "$GATE" hook
  rc=$?
else
  rc=127
fi
set -e
if [ "$rc" = 0 ] || [ "$rc" = 2 ]; then
  exit "$rc"
fi
# The gate could not run. A dispatch from a ledger thread without any
# `serves:` is denied by shape alone; the rest is allowed.
if printf '%s' "$input" | grep -qE 'fleet_member_(spawn|tell)|fleet_delegate|thread[^"]{0,40}(spawn|create|tell|message)' \
   && ! printf '%s' "$input" | grep -qiE 'serves:[[:space:]]*(P[0-9]|revision)'; then
  echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "[scope-gate] gate could not run and this dispatch names no purpose; add `serves: P<n>` for one of the ledger'"'"'s open purposes"}}'
  echo "[scope-gate] gate could not run; dispatch without serves: denied" >&2
  exit 2
fi
exit 0
