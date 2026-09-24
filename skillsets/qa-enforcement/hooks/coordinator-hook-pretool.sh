#!/bin/sh
# pretool adapter for coordinator-mode (no argv: Codex runs hook commands as a path).
# Since 2026-09-24 the QA ship gate runs first: it denies ship commands
# (git push, gh pr create/merge, bb fleet validate, deploys) in repos that
# opted in with a committed .qa/config.json, and allows everything else.
# Non-ship behaviour is unchanged: it falls through to coordinator-hook.sh,
# which still blocks coordinator-mode edits exactly as before.
input=$(cat)
printf '%s' "$input" | "$HOME/.agent-hooks/qa-ship-gate-hook.sh"
rc=$?
if [ "$rc" = 2 ]; then
  exit 2
fi
printf '%s' "$input" | exec "$HOME/.agent-hooks/coordinator-hook.sh" pretool
