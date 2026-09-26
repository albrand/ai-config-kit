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
# --- scope shape (identical in coordinator-hook-pretool.sh and scope-gate-hook.sh;
# test-hook-chain.sh checks the two copies match) ---
# A dispatch-shaped call from a thread with a scope ledger is allowed only
# when it names an OPEN purpose (serves: P<n>) or quotes an accepted revision;
# an unknown or blocked id does not count. The ledger is read with jq; no jq
# or an unreadable ledger serves nothing (fails closed, as the gate does).
# The payload without quotes and backslashes, so `bb thr"ead"` reads as run.
scope_flat() { printf '%s' "$input" | tr -d '\\"'"'"; }

# 0 when the call must be denied.
scope_dispatch_denied() {
  [ -n "${BB_THREAD_ID:-}" ] || return 1
  _ledger="${SCOPE_LEDGER_DIR:-$HOME/.local/state/agent-quality/scope}/$BB_THREAD_ID.json"
  [ -f "$_ledger" ] || return 1
  _f=$(scope_flat)
  printf '%s' "$_f" | grep -qiE 'fleet_member_(spawn|tell)|fleet_delegate|thread.{0,40}(spawn|create|fork|tell|message|edit-message|queue)|fleet.{0,20}(group-create|task-add|advise)' || return 1
  _open=$(jq -r '.purposes[] | select(.status == "open") | .id' "$_ledger" 2>/dev/null) || return 0
  for _id in $(printf '%s' "$_f" | grep -oiE 'serves: *P[0-9]+([ ,/&+]+(and +)?P[0-9]+)*' | grep -oiE 'P[0-9]+' | tr 'p' 'P'); do
    printf '%s\n' "$_open" | grep -qx "$_id" && return 1
  done
  if printf '%s' "$_f" | grep -qiE 'serves: *revision'; then
    jq -r '.accepted_revisions[]?.quote' "$_ledger" 2>/dev/null | tr -d '\\"'"'" | while IFS= read -r _q; do
      [ -n "$_q" ] && printf '%s' "$_f" | grep -qF -- "$_q" && exit 7
    done
    [ $? = 7 ] && return 1
  fi
  return 0
}
# --- end scope shape ---
flat=$(scope_flat)
# Cheap prefilter: no dispatch shape anywhere in the payload, nothing to gate.
printf '%s' "$flat" | grep -qiE 'fleet_member_|fleet_delegate|thread|fleet' || exit 0
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
# The gate could not run: decide by shape alone (an open purpose or an
# accepted revision, read from the ledger with jq).
if scope_dispatch_denied; then
  echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "[scope-gate] gate could not run and this dispatch names no open purpose; add `serves: P<n>` for one of the ledger'"'"'s open purposes"}}'
  echo "[scope-gate] gate could not run; dispatch without an open purpose denied" >&2
  exit 2
fi
exit 0
