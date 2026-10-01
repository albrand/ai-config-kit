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
# Compute both checks before one bounded retry. A formatting nudge must not
# hide unfinished work until stop_hook_active lets the retry end.
closeout="$HOME/.agents/skills/scope-ledger/scripts/closeout-stop.py"
result='{}'
if [ -f "$closeout" ]; then
  result=$(printf '%s' "$payload" | python3 "$closeout") || result='{}'
fi
QA_STOP_EVIDENCE="$evidence" QA_STOP_CLOSEOUT="$result" python3 -c '
import json,os
reasons=[]
for key in ("QA_STOP_EVIDENCE", "QA_STOP_CLOSEOUT"):
    try:
        result=json.loads(os.environ[key])
    except (ValueError, KeyError):
        continue
    if isinstance(result,dict) and result.get("decision")=="block":
        reasons.append(result["reason"])
if reasons:
    print(json.dumps({"decision":"block","reason":"\n\n".join(reasons)}))
'
