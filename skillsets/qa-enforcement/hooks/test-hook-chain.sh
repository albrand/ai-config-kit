#!/bin/sh
# T2: the PreToolUse chain decides before the host's hook timeout even when a
# stage is slow. A timed-out hook lets the command run (Claude Code 2.1.282
# probed live, Codex 0.157.0 from source, 2026-09-25), so a chain the host has
# to kill is a fail-open.
#
# Builds a scratch HOME with the kit's coordinator-hook-pretool.sh and
# scope-gate-hook.sh, the kit's scope-ledger skill, a ledger for a scratch
# thread, and a stub ship gate that sleeps. Each case sends a payload through
# the chain under the timeout the host config gives the chain entry. Every case
# runs twice: with python3 as it is, and with a python3 that takes 3.5 s more to
# start, the worst stage cost review r1 measured at load 160-213; the verdict
# must not depend on how loaded this host is.
#   usage: test-hook-chain.sh [host-config]   (default ~/.claude/settings.json)
set -u
HOOKS="$(cd "$(dirname "$0")" && pwd)"
SKILL="$HOOKS/../shared/scope-ledger"
CFG="${1:-$HOME/.claude/settings.json}"
T=$(jq -r '[.hooks.PreToolUse[]?.hooks[]? | select(.command | endswith("coordinator-hook-pretool.sh")) | .timeout] | min // empty' "$CFG")
[ -n "$T" ] || { echo "FAIL no coordinator-hook-pretool.sh entry in $CFG"; exit 1; }
fails=0
# The chain's own deadlines leave the host timeout a margin, and the two
# copies of the shell shape decision are the same text.
chain=$(sed -n 's/^CHAIN_DEADLINE=//p' "$HOOKS/coordinator-hook-pretool.sh")
if ! perl -e 'exit !($ARGV[0] + 2 <= $ARGV[1])' "$chain" "$T"; then
  echo "FAIL CHAIN_DEADLINE $chain s leaves under 2 s before the host timeout $T s"; fails=$((fails + 1))
fi
a=$(sed -n '/^# --- scope shape/,/^# --- end scope shape/p' "$HOOKS/coordinator-hook-pretool.sh" | shasum)
b=$(sed -n '/^# --- scope shape/,/^# --- end scope shape/p' "$HOOKS/scope-gate-hook.sh" | shasum)
[ -n "$(sed -n '/^# --- scope shape/p' "$HOOKS/scope-gate-hook.sh")" ] && [ "$a" = "$b" ] \
  || { echo "FAIL the scope shape blocks in coordinator-hook-pretool.sh and scope-gate-hook.sh differ"; fails=$((fails + 1)); }
H=$(mktemp -d "${TMPDIR:-/tmp}/hook-chain-test.XXXXXX")
trap 'rm -rf "$H"' EXIT
mkdir -p "$H/.agent-hooks" "$H/.agents/skills" "$H/.local/state/agent-quality/scope" "$H/slowpy"
cp "$HOOKS/coordinator-hook-pretool.sh" "$HOOKS/scope-gate-hook.sh" "$H/.agent-hooks/"
cp -R "$SKILL" "$H/.agents/skills/scope-ledger"
THR=$(jq -r .thread_id "$SKILL/tests/fixtures/scope-ledger.json")
cp "$SKILL/tests/fixtures/scope-ledger.json" "$H/.local/state/agent-quality/scope/$THR.json"
printf '#!/bin/sh\ncat >/dev/null\nexit 0\n' > "$H/.agent-hooks/coordinator-hook.sh"
printf '#!/bin/sh\nsleep 3.5\nexec %s "$@"\n' "$(python3 -c "import sys; print(sys.executable)")" > "$H/slowpy/python3"
chmod +x "$H/.agent-hooks/"*.sh "$H/slowpy/python3"
ms() { perl -MTime::HiRes=time -e 'printf "%d", time*1000'; }
# The two deadline decisions agree (review r2b): the shell's jq shape, from
# this kit's coordinator-hook-pretool.sh, and scope-gate.py `shape`, over
# tests/fixtures/shape-cases.json. Only the call's own words count.
sed -n '/^# --- scope shape/,/^# --- end scope shape/p' "$HOOKS/coordinator-hook-pretool.sh" > "$H/shape.sh"
# Plus, from scope-gate.py's MCP_FIELDS, every gated agent tool without a
# serves line (deny) and with one in each of its fields in turn (allow), so
# the jq copy of the tool and field lists cannot drift from Python's.
python3 - "$SKILL/scripts/scope-gate.py" "$SKILL/tests/fixtures/shape-cases.json" > "$H/shape-cases.json" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("sg", sys.argv[1]); sg = importlib.util.module_from_spec(spec); spec.loader.exec_module(sg)
cases = json.load(open(sys.argv[2]))["cases"]
for tool, fields in sg.MCP_FIELDS.items():
    base = {f: "go on" for f in fields}
    cases.append({"label": f"{tool} without serves", "want": 2, "payload": {"tool_name": f"mcp__bb-bridge__{tool}", "tool_input": base}})
    for f in fields:
        cases.append({"label": f"{tool} serving P1 in {f}", "want": 0,
                      "payload": {"tool_name": f"mcp__bb-bridge__{tool}", "tool_input": {**base, f: "serves: P1 go on"}}})
print(json.dumps({"cases": cases}))
PY
n=$(jq '.cases | length' "$H/shape-cases.json")
i=0
while [ "$i" -lt "$n" ]; do
  label=$(jq -r ".cases[$i].label" "$H/shape-cases.json")
  want=$(jq -r ".cases[$i].want" "$H/shape-cases.json")
  payload=$(jq -c ".cases[$i].payload" "$H/shape-cases.json")
  sh_rc=$(input="$payload" BB_THREAD_ID="$THR" SCOPE_LEDGER_DIR="$H/.local/state/agent-quality/scope" \
    sh -c '. "$1"; if scope_dispatch_denied; then echo 2; else echo 0; fi' _ "$H/shape.sh")
  py=$(printf '%s' "$payload" | BB_THREAD_ID="$THR" SCOPE_LEDGER_DIR="$H/.local/state/agent-quality/scope" \
    python3 "$SKILL/scripts/scope-gate.py" shape)
  py_rc=$([ "$py" = deny ] && echo 2 || echo 0)
  if [ "$sh_rc" = "$want" ] && [ "$py_rc" = "$want" ]; then
    echo "ok   shape: $label: shell=$sh_rc python=$py_rc"
  else
    echo "FAIL shape: $label: shell=$sh_rc python=$py_rc ($py) want $want"
    fails=$((fails + 1))
  fi
  i=$((i + 1))
done
# Every gated agent tool, without a serves line, is denied through the whole
# chain (the scope-gate-hook.sh prefilter must not let one through unread).
printf '#!/bin/sh\ncat >/dev/null\nexit 0\n' > "$H/.agent-hooks/qa-ship-gate-hook.sh"
chmod +x "$H/.agent-hooks/qa-ship-gate-hook.sh"
# No jq (or no answer from it): the grep fallback denies every case the jq
# shape denies (it is broader: any dispatch word, fails closed).
mkdir -p "$H/nojq"
printf '#!/bin/sh\nexit 1\n' > "$H/nojq/jq"
chmod +x "$H/nojq/jq"
for i in $(jq -r '.cases | to_entries[] | select(.value.want == 2) | .key' "$H/shape-cases.json"); do
  label=$(jq -r ".cases[$i].label" "$H/shape-cases.json")
  payload=$(jq -c ".cases[$i].payload" "$H/shape-cases.json")
  fb=$(input="$payload" PATH="$H/nojq:$PATH" BB_THREAD_ID="$THR" SCOPE_LEDGER_DIR="$H/.local/state/agent-quality/scope" \
    sh -c '. "$1"; if scope_dispatch_denied; then echo 2; else echo 0; fi' _ "$H/shape.sh")
  if [ "$fb" = 2 ]; then
    echo "ok   no-jq fallback: $label"
  else
    echo "FAIL no-jq fallback allowed: $label"
    fails=$((fails + 1))
  fi
done
for tool in $(jq -r '.cases[].payload.tool_name | select(startswith("mcp__bb-bridge__"))' "$H/shape-cases.json" | sort -u); do
  payload=$(jq -c --arg t "$tool" '[.cases[] | select(.payload.tool_name == $t and .want == 2)][0].payload' "$H/shape-cases.json")
  [ "$payload" = null ] && continue
  printf '%s' "$payload" | HOME="$H" BB_THREAD_ID="$THR" perl -e 'alarm shift; exec @ARGV' "$T" \
    sh "$H/.agent-hooks/coordinator-hook-pretool.sh" >"$H/out" 2>"$H/err"
  rc=$?
  if [ "$rc" = 2 ] && grep -q "must say which" "$H/err"; then
    echo "ok   chain: $tool without serves: denied by the gate"
  else
    echo "FAIL chain: $tool without serves: rc=$rc [$(tr '\n' ' ' < "$H/err" | cut -c1-70)]"
    fails=$((fails + 1))
  fi
done
bash_payload() { jq -nc --arg c "$1" '{tool_name:"Bash",tool_input:{command:$c},cwd:"/tmp"}'; }
# case: <ship stage seconds>|<want rc>|<reason the deny must carry, or ->|<command>
# The chain kills a gate stage 11 s after HOOK_T0 and decides by shape in
# shell ("could not finish"); a gate reached after that is not started.
# `slow` gives the reason for the slow-python run where it differs. A 30 s
# stage outlives the host timeout: only killing it at the deadline answers in time.
cases='0|2|must say|bb thread tell thr_x also refactor it
0|2|must say|bb thr"ead" tell thr_x also refactor it
0|2|must say|BB thread tell thr_x also refactor it
0|2|must say|bb thread fork thr_x --prompt also refactor it
0|2|must say|bb fleet group-create g --charter also refactor it
0|0|-|bb thread tell thr_x serves: P1 next step
0|0|-|ls -la
8|2|-|bb thread tell thr_x also refactor it
11.8|2|could not finish|bb thread tell thr_x also refactor it
13|2|could not finish|bb thread tell thr_x also refactor it
13|2|could not finish|bb thr"ead" tell thr_x also refactor it
13|2|could not finish|bb thread tell thr_x serves: P2 which is blocked
13|2|could not finish|bb thread tell thr_x serves: P9 unknown
13|0|-|bb thread tell thr_x serves: P1 next step
13|0|-|ls -la
13|2|Ship denied|git push origin main
30|2|could not finish|bb thread tell thr_x also refactor it
30|0|-|ls -la
13|2|could not finish|bb thread tell thr_x also refactor it # serves: P1
0|2|must say|bb automation create --project p --name n --in 1m --prompt also refactor it
0|2|must say|bb instructions set also refactor it
0|0|-|bb automation create --project p --name n --in 1m --prompt serves: P1 next step
0|2|must say|bb thread tell thr_x serves: P1 next; bb thread tell thr_y also refactor it
13|2|could not finish|bb automation create --project p --name n --in 1m --prompt also refactor it
13|2|could not finish|bb instructions set also refactor it
13|2|could not finish|bb thread tell thr_x serves: P1 next; bb thread tell thr_y also refactor it
13|0|-|bb instructions set serves: P1 keep the QA gates'
# review r2b: a FIFO brief is not opened (it blocked the gate until its deadline)
mkfifo "$H/brief.fifo"
cases="$cases
0|2|not a regular file|bb thread tell thr_x --message-file $H/brief.fifo"
for mode in plain slowpy; do
  path="$PATH"
  [ "$mode" = slowpy ] && path="$H/slowpy:$PATH"
  while IFS='|' read -r slow want why cmd; do
    printf '#!/bin/sh\ncat >/dev/null\nsleep %s\nexit 0\n' "$slow" > "$H/.agent-hooks/qa-ship-gate-hook.sh"
    chmod +x "$H/.agent-hooks/qa-ship-gate-hook.sh"
    # with python 3.5 s slower a normal decision may become a shape one
    [ "$mode" = slowpy ] && [ "$why" = "must say" ] && why=-
    a=$(ms)
    bash_payload "$cmd" | PATH="$path" HOME="$H" BB_THREAD_ID="$THR" perl -e 'alarm shift; exec @ARGV' "$T" \
      sh "$H/.agent-hooks/coordinator-hook-pretool.sh" >"$H/out" 2>"$H/err"
    rc=$?
    took=$(( $(ms) - a ))
    label="$mode, ship stage ${slow}s, [$cmd]"
    if [ "$rc" = 142 ]; then
      echo "FAIL $label: the host timeout (${T}s) killed the chain at ${took} ms; the command would run"
      fails=$((fails + 1))
    elif [ "$rc" != "$want" ]; then
      echo "FAIL $label: rc=$rc in ${took} ms, want $want before ${T}s [$(tr '\n' ' ' < "$H/err" | cut -c1-70)]"
      fails=$((fails + 1))
    elif [ "$why" != - ] && ! grep -q "$why" "$H/err"; then
      echo "FAIL $label: denied, but not by \"$why\" [$(tr '\n' ' ' < "$H/err" | cut -c1-70)]"
      fails=$((fails + 1))
    else
      echo "ok   $label: rc=$rc in ${took} ms (host timeout ${T}s) [$(tr '\n' ' ' < "$H/err" | cut -c1-60)]"
    fi
  done 2>/dev/null <<EOF
$cases
EOF
done
echo "hook chain test: $([ $fails = 0 ] && echo "all pass" || echo "$fails FAIL") (config $CFG, timeout ${T}s, load $(sysctl -n vm.loadavg 2>/dev/null))"
[ $fails = 0 ]
