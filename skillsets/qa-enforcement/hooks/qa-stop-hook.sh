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
# Token-cost rules (owner, 2026-11-17: "draining tokens like a drunk elder man
# at the desert"). Each nudge re-sends the whole context, so:
# 1. On a Stop retry only keep-going (K1) may block again, by its own per-turn
#    cap; the evidence nudge never adds a second or third full-context turn.
retry=no
if printf '%s' "$payload" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("stop_hook_active") else 1)' 2>/dev/null; then
  retry=yes
fi
# 2. Watched background work (a live run_in_background task) is not an early stop.
# 3. A chat-only turn (no tool call since the last prompt) skips the evidence
#    nudge only; keep-going and closeout still check it.
state=$(printf '%s' "$payload" | python3 -I "$HOME/.agent-hooks/stop-state.py" 2>/dev/null) || state=unknown
[ "$state" = background ] && exit 0
if [ "$state" = chat ] || [ "$retry" = yes ]; then
  evidence='{}'
else
  evidence=$(printf '%s' "$payload" | python3 "$HOME/.agents/skills/qa-sweep/scripts/evidence-stop.py") || exit 0
fi
# Compute both checks before one bounded retry. A formatting nudge must not
# hide unfinished work until stop_hook_active lets the retry end.
closeout="$HOME/.agents/skills/scope-ledger/scripts/closeout-stop.py"
result='{}'
if [ -f "$closeout" ]; then
  result=$(printf '%s' "$payload" | python3 "$closeout") || result='{}'
fi
keepgoing="$HOME/.agent-hooks/keepgoing-stop.py"
nudge='{}'
if [ -f "$keepgoing" ]; then
  nudge=$(printf '%s' "$payload" | python3 "$keepgoing") || nudge='{}'
fi
QA_STOP_EVIDENCE="$evidence" QA_STOP_CLOSEOUT="$result" QA_STOP_KEEPGOING="$nudge" python3 -c '
import json,os
reasons=[]
for key in ("QA_STOP_EVIDENCE", "QA_STOP_CLOSEOUT", "QA_STOP_KEEPGOING"):
    try:
        result=json.loads(os.environ[key])
    except (ValueError, KeyError):
        continue
    if isinstance(result,dict) and result.get("decision")=="block":
        reasons.append(result["reason"])
if reasons:
    print(json.dumps({"decision":"block","reason":"\n\n".join(reasons)}))
'
