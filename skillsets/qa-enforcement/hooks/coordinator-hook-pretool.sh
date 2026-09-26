#!/bin/sh
# pretool adapter for coordinator-mode (no argv: Codex runs hook commands as a path).
# Since 2026-09-24 the QA ship gate runs first: it denies ship commands
# (git push, gh pr create/merge, bb fleet validate, deploys) in repos that
# opted in with a committed .qa/config.json, and allows everything else.
# Since 2026-09-25 the scope gate runs second: from a thread with a scope
# ledger, a spawn or tell must say which open purpose it serves.
# Non-ship behaviour is unchanged: it falls through to coordinator-hook.sh,
# which still blocks coordinator-mode edits exactly as before.
#
# One clock for the whole chain, and this script holds it. A PreToolUse hook
# the host times out does not block: the command runs (Claude Code 2.1.282
# probed live; Codex 0.157.0 pre_tool_use.rs). A gate that keeps its own
# deadline in Python only starts keeping it after sh, the wrapper and the
# interpreter are up, which cost 2-3.5 s at load 160-213 (review r1). So each
# stage runs under a supervisor here: a gate stage still running
# GATE_DEADLINE s after HOOK_T0 is killed with its whole process group and
# the command is decided by shape in this shell, with no Python; a gate stage
# reached after the deadline is not started at all. The last stage is cut at
# CHAIN_DEADLINE and fails open, as a host timeout would, but inside it.
# Budget (host timeout 15 s, hooks/hook-timeouts.py): shell start before
# HOOK_T0 plus the shape decision plus exit stay under 3 s at load ~200.
GATE_DEADLINE=11
CHAIN_DEADLINE=12.5
HOOK_T0=$(perl -MTime::HiRes=time -e 'printf "%.3f", time' 2>/dev/null)
export HOOK_T0
input=$(cat)
H="$HOME/.agent-hooks"

# run <deadline> <command...>: stdin passes through. 124 when the deadline
# had passed or the stage was killed at it; otherwise the stage's own rc.
run() {
  perl -MTime::HiRes=time,alarm -e '
    my $left = shift(@ARGV) - (time - $ENV{HOOK_T0});
    exit 124 if $left <= 0;
    my $pid = fork;
    exit 125 unless defined $pid;
    if (!$pid) { setpgrp(0, 0); exec { $ARGV[0] } @ARGV; exit 127 }
    setpgrp($pid, $pid);
    $SIG{ALRM} = sub { kill "KILL", -$pid; kill "KILL", $pid; waitpid($pid, 0); exit 124 };
    alarm $left;
    waitpid($pid, 0);
    alarm 0;
    exit(($? & 127) ? 128 + ($? & 127) : $? >> 8);
  ' "$@"
}
if [ -z "$HOOK_T0" ]; then  # no perl: no supervisor, the stages run as before
  run() { shift; "$@"; }
fi

deny() {
  printf '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "%s"}}\n' "$1"
  printf '%s\n' "$1" >&2
  exit 2
}
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

# Ship shape (the ship gate's coarse classes). At the deadline a ship-shaped
# command is denied whether or not its repo opted in: there was no time to read.
ship_shape() {
  scope_flat | grep -qE 'git( [^ ;&|]+)* push|gh pr (merge|ready)|gh (release (create|edit)|workflow run)|vercel[^;&|]*(--prod|--target[= ]production|promote|redeploy|alias|rolling-release)|netlify[^;&|]*deploy[^;&|]*--prod|fly(ctl)? deploy|/v[0-9]+/deployments|/v[0-9]+/projects/[^ ]*/promote/|repos/[^ ]*/(pulls/[0-9]+/merge|merges|releases|git/refs|dispatches|contents/|deployments)|mergePullRequest|createCommitOnBranch|updateRef'
}
LATE="the hook chain could not finish within $GATE_DEADLINE s of starting (the host's hook timeout is 15 s, and a timed-out hook lets the command run)"

printf '%s' "$input" | run "$GATE_DEADLINE" "$H/qa-ship-gate-hook.sh"
rc=$?
[ "$rc" = 2 ] && exit 2
if [ "$rc" = 124 ] && ship_shape; then
  deny "[qa-ship-gate] Ship denied: $LATE; this command is ship-shaped, so it is denied. Retry it."
fi
if [ -x "$H/scope-gate-hook.sh" ]; then
  printf '%s' "$input" | run "$GATE_DEADLINE" "$H/scope-gate-hook.sh"
  rc=$?
  [ "$rc" = 2 ] && exit 2
  if [ "$rc" = 124 ] && scope_dispatch_denied; then
    deny "[scope-gate] the gate could not finish: $LATE; this dispatch names no open purpose, so it is denied: add serves: P<n> and retry"
  fi
fi
printf '%s' "$input" | run "$CHAIN_DEADLINE" "$H/coordinator-hook.sh" pretool
[ $? = 2 ] && exit 2
exit 0
