#!/bin/zsh
# Health snapshot for an orchestrator running through elyra-acp. Prints one
# line per check: OK, WARN or FAIL, so a watcher can act on anything not OK.
# Usage: fleet-health.sh <bb thread id> <claude session id>
thread=$1 session=$2
log=~/.local/state/elyra-acp/bridge.log
storage=~/.bb/thread-storage/$thread
transcript=$(ls ~/.claude/projects/*/$session.jsonl 2>/dev/null | head -1)
now=$(date +%s)

bbstate=$(bb thread show $thread 2>&1 | sed -n 2p | awk '{print $2}')
case $bbstate in idle|active) echo "OK   bb status $bbstate";; *) echo "FAIL bb status ${bbstate:-unknown}";; esac

if [ -n "$transcript" ]; then
  age=$(( now - $(stat -f %m "$transcript") ))
  if [ "$bbstate" = active ] && [ $age -gt 900 ]; then echo "WARN transcript quiet ${age}s while bb says active"; else echo "OK   transcript age ${age}s"; fi
else echo "FAIL transcript for $session not found"; fi

recent=$(grep "\"thread\":\"$thread\"" $log | tail -200)
errs=$(echo "$recent" | grep -c '"event":"error"')
gate=$(echo "$recent" | grep '"event":"gate"' | tail -1 | grep -o '"gate":"[^"]*"')
lastgate_t=$(echo "$recent" | grep '"event":"gate"' | tail -1 | grep -o '"t":"[^"]*"' | cut -d'"' -f4)
lastsent_t=$(echo "$recent" | grep '"event":"prompt-sent"' | tail -1 | grep -o '"t":"[^"]*"' | cut -d'"' -f4)
[ "$errs" -gt 0 ] && echo "WARN bridge errors in recent log: $errs ($(echo "$recent" | grep '"event":"error"' | tail -1 | grep -o '"error":"[^"]\{0,160\}'))" || echo "OK   no bridge errors"
if [ -n "$lastgate_t" ] && [[ "$lastgate_t" > "$lastsent_t" ]]; then echo "WARN waiting on a prompt in Elyra: $gate"; else echo "OK   no open Elyra prompt"; fi

if [ -f $storage/PLAN.md ]; then
  page=$(( now - $(stat -f %m $storage/PLAN.md) ))
  [ $page -gt 21600 ] && echo "WARN PLAN.md not updated for $((page/3600))h" || echo "OK   PLAN.md age $((page/60))m"
else echo "FAIL PLAN.md missing"; fi

ledger=~/.local/state/agent-quality/scope/$thread.json
[ -f $ledger ] && echo "OK   scope ledger present ($(python3 -c "import json;d=json.load(open('$ledger'));print(sum(p.get('status')=='open' for p in d['purposes']),'open purposes')"))" || echo "FAIL scope ledger missing"

orphans=$(bb thread list --project proj_d7xhqan8mu --json 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
import os; m=json.load(open(os.path.expanduser('~/.local/state/elyra-acp/migrations.json'))) if os.path.exists(os.path.expanduser('~/.local/state/elyra-acp/migrations.json')) else {}
print(sum(1 for t in d if t.get('parentThreadId')=='thr_vr4dga9uxn' and not t.get('archivedAt') and t['id'] not in m))" 2>/dev/null)
[ "${orphans:-0}" -gt 0 ] && echo "WARN $orphans live children still point at the stopped thr_vr4dga9uxn" || echo "OK   no children left on the old thread"

old=$(bb thread show thr_vr4dga9uxn 2>&1 | sed -n 2p | awk '{print $2}')
[ "$old" = active ] && echo "FAIL old thread thr_vr4dga9uxn is active again (two writers)" || echo "OK   old thread stays $old"

# Every child moved onto the bridge: bb state, recent bridge errors, open prompts.
python3 - "$log" <<'PY'
import json, os, subprocess, sys, time
mig = json.load(open(os.path.expanduser("~/.local/state/elyra-acp/migrations.json"))) if os.path.exists(os.path.expanduser("~/.local/state/elyra-acp/migrations.json")) else {}
lines = open(sys.argv[1]).read().splitlines()[-4000:]
cut = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(time.time() - 1800))
for old, r in mig.items():
    new = r.get("new")
    if not new: print(f"WARN migration of {old} incomplete: {r.get('error','no new thread')}"); continue
    st = subprocess.run(["bb", "thread", "show", new], capture_output=True, text=True).stdout.splitlines()
    state = st[1].split()[-1] if len(st) > 1 else "unknown"
    mine = [json.loads(l) for l in lines if f'"thread":"{new}"' in l]
    errs = [e for e in mine if e["event"] == "error" and e["t"] >= cut]
    gates = [e for e in mine if e["event"] == "gate"]
    sent = [e for e in mine if e["event"] == "prompt-sent"]
    open_gate = gates and (not sent or gates[-1]["t"] > sent[-1]["t"])
    flag = "FAIL" if state not in ("idle", "active") else "WARN" if errs or open_gate else "OK  "
    note = (f" errors={len(errs)} last={errs[-1]['error'][:120]}" if errs else "") + (f" waiting: {gates[-1].get('gate')}" if open_gate else "")
    print(f"{flag} child {new} (was {old}) {state}{note}")
PY
