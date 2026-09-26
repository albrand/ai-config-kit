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
30|0|-|ls -la'
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
