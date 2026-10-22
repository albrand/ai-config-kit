#!/bin/sh
# PostToolUse (Claude Code and Codex, same schema): a coordinator that keeps staffing work with
# no gap map is shown the delivery contract (scope-gate.py nudge). Never denies; any failure is
# silent. Owner-approved 2026-10-22.
# Python starts only for a thread with a scope ledger, within 2 minutes of one of its dispatches
# passing the gate (scope-gate.py touches scope-passed/<thread> then). Every other tool call
# leaves here. Not the shared decision log's tail: the whole fleet writes it (review of #92).
DIR="${SCOPE_LEDGER_DIR:-$HOME/.local/state/agent-quality/scope}"
MARK="$HOME/.local/state/agent-quality/scope-passed/${BB_THREAD_ID:-none}"
GATE="$HOME/.agents/skills/scope-ledger/scripts/scope-gate.py"
[ -n "${BB_THREAD_ID:-}" ] && [ -f "$DIR/$BB_THREAD_ID.json" ] && [ -f "$GATE" ] || exit 0
[ -n "$(find "$MARK" -mmin -2 2>/dev/null)" ] || exit 0
exec python3 "$GATE" nudge 2>/dev/null
