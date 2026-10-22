#!/bin/sh
# PostToolUse (Claude Code and Codex, same schema): a coordinator that keeps staffing work with
# no gap map is shown the delivery contract (scope-gate.py nudge). Never denies; any failure is
# silent. Owner-approved 2026-10-22.
# Python starts only for a thread with a scope ledger, right after one of its dispatches passed
# the gate (scope-gate.py logs each as scope_passed). Every other tool call leaves here.
DIR="${SCOPE_LEDGER_DIR:-$HOME/.local/state/agent-quality/scope}"
LOG="$HOME/.local/state/agent-quality/scope-decisions.jsonl"
GATE="$HOME/.agents/skills/scope-ledger/scripts/scope-gate.py"
[ -n "${BB_THREAD_ID:-}" ] && [ -f "$DIR/$BB_THREAD_ID.json" ] && [ -f "$GATE" ] || exit 0
tail -n 30 "$LOG" 2>/dev/null | grep -q "\"scope_passed\", \"thread\": \"$BB_THREAD_ID\"" || exit 0
exec python3 "$GATE" nudge 2>/dev/null
