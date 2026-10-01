#!/bin/sh
# Stop-hook adapter for the QA sweep, the default-on evidence nudge and the
# scope-ledger closeout check (open purposes with nothing carrying them).
# The evidence nudge runs in every repo, without creating .qa files or denying
# tools. The existing ship gate remains opted-in through .qa/config.json.
payload=$(cat)
# Preserve the opted-in inventory gate's priority. Its block must be reported
# before the evidence nudge can cause a Stop retry with stop_hook_active=true.
inventory=$(printf '%s' "$payload" | python3 "$HOME/.agents/skills/qa-sweep/scripts/ship-gate.py" stop)
if printf '%s' "$inventory" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("decision")=="block" else 1)' 2>/dev/null; then
  printf '%s\n' "$inventory"
  exit 0
fi
evidence=$(printf '%s' "$payload" | python3 "$HOME/.agents/skills/qa-sweep/scripts/evidence-stop.py") || exit 0
if printf '%s' "$evidence" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("decision")=="block" else 1)' 2>/dev/null; then
  printf '%s\n' "$evidence"
  exit 0
fi
# One nudge per turn: the closeout check runs only when the evidence nudge did not block.
closeout="$HOME/.agents/skills/scope-ledger/scripts/closeout-stop.py"
[ -f "$closeout" ] || exit 0
result=$(printf '%s' "$payload" | python3 "$closeout") || exit 0
if printf '%s' "$result" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("decision")=="block" else 1)' 2>/dev/null; then
  printf '%s\n' "$result"
fi
