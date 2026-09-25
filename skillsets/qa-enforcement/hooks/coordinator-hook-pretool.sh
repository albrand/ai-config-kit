#!/bin/sh
# pretool adapter for coordinator-mode (no argv: Codex runs hook commands as a path).
# Since 2026-09-24 the QA ship gate runs first: it denies ship commands
# (git push, gh pr create/merge, bb fleet validate, deploys) in repos that
# opted in with a committed .qa/config.json, and allows everything else.
# Since 2026-09-25 the scope gate runs second: from a thread with a scope
# ledger, a spawn or tell must say which open purpose it serves.
# Non-ship behaviour is unchanged: it falls through to coordinator-hook.sh,
# which still blocks coordinator-mode edits exactly as before.
# One clock for the whole chain: the gates' deadlines count from here, so
# interpreter start-up and earlier stages spend the same budget, which ends
# before the host's hook timeout (a timed-out hook lets the command run).
HOOK_T0=$(perl -MTime::HiRes=time -e 'printf "%.3f", time' 2>/dev/null)
export HOOK_T0
input=$(cat)
printf '%s' "$input" | "$HOME/.agent-hooks/qa-ship-gate-hook.sh"

rc=$?
if [ "$rc" = 2 ]; then
  exit 2
fi
if [ -x "$HOME/.agent-hooks/scope-gate-hook.sh" ]; then
  printf '%s' "$input" | "$HOME/.agent-hooks/scope-gate-hook.sh"
  rc=$?
  if [ "$rc" = 2 ]; then
    exit 2
  fi
fi
printf '%s' "$input" | exec "$HOME/.agent-hooks/coordinator-hook.sh" pretool
