#!/bin/sh
# PreToolUse adapter for the QA ship gate (Claude Code + Codex via
# coordinator-hook-pretool.sh). Reads the hook payload on stdin.
#   exit 0 + no output = allow; exit 2 + JSON/stderr = deny.
# Fails OPEN except for ship commands in .qa-opted-in repos, where the python
# gate denies on any internal error (fail closed). If python itself is
# missing, a POSIX grep fallback still denies ship commands generically so the
# fail-closed property does not depend on the interpreter being present.
GATE="$HOME/.agents/skills/qa-sweep/scripts/ship-gate.py"
input=$(cat)
set +e
if [ -f "$GATE" ]; then
  printf '%s' "$input" | python3 "$GATE" hook
  rc=$?
else
  # v4: `python3 <missing file>` exits 2, which read as a DENY of every
  # command (ls included); a missing gate goes to the shape fallback instead
  rc=127
fi
set -e
if [ "$rc" = 0 ] || [ "$rc" = 2 ]; then
  exit "$rc"
fi
# python missing or crashed before it could decide: decide by shape alone.
# v4: releases (v5: gh release edit too), workflow dispatch and deployments-API
# posts join the coarse shapes (any git push already covers tags/--tags/--mirror); the shapes match
# anywhere in the command (`cd x && git push` included), and fly(ctl) is a
# real alternation (the old `flyctl\?` only matched a literal "?").
if printf '%s' "$input" | grep -qE '"command"[^:]*:[^"]*"[^"]*(git [^"]*push|gh pr (merge|ready)|gh (release (create|edit)|workflow run)|vercel[^"]*(--prod|--target[= ]production|promote|redeploy|alias|rolling-release)|netlify[^"]*deploy[^"]*--prod|fly(ctl)? deploy|/v[0-9]+/deployments|/v[0-9]+/projects/[^"]*/promote/|repos/[^"]*/(pulls/[0-9]+/merge|merges|releases|git/refs|dispatches|contents/|deployments)|mergePullRequest|createCommitOnBranch|updateRef)'; then
  echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "[qa-ship-gate] gate could not run but a ship command was attempted; treat as denied and complete the .qa pipeline"}}' 
  echo "[qa-ship-gate] gate could not run; ship treated as denied" >&2
  exit 2
fi
exit 0
