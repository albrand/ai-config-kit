#!/bin/sh
# T2: the PreToolUse chain decides before the host's hook timeout even when an
# earlier stage is slow. A timed-out hook lets the command run (Claude Code
# 2.1.282 probed live, Codex 0.157.0 from source, 2026-09-25), so a chain the
# host has to kill is a fail-open.
#
# Builds a scratch HOME with the kit's coordinator-hook-pretool.sh and
# scope-gate-hook.sh, the kit's scope-ledger skill, a ledger for a scratch
# thread, and a stub ship gate that sleeps. Each case sends a payload through
# the chain under the timeout the host config gives the chain entry; an
# undeclared dispatch must end in a deny before it, the rest in an allow.
#   usage: test-hook-chain.sh [host-config]   (default ~/.claude/settings.json)
set -u
HOOKS="$(cd "$(dirname "$0")" && pwd)"
SKILL="$HOOKS/../shared/scope-ledger"
CFG="${1:-$HOME/.claude/settings.json}"
T=$(jq -r '[.hooks.PreToolUse[]?.hooks[]? | select(.command | endswith("coordinator-hook-pretool.sh")) | .timeout] | min // empty' "$CFG")
[ -n "$T" ] || { echo "FAIL no coordinator-hook-pretool.sh entry in $CFG"; exit 1; }
H=$(mktemp -d /tmp/hook-chain-test.XXXXXX)
trap 'rm -rf "$H"' EXIT
mkdir -p "$H/.agent-hooks" "$H/.agents/skills" "$H/.local/state/agent-quality/scope"
cp "$HOOKS/coordinator-hook-pretool.sh" "$HOOKS/scope-gate-hook.sh" "$H/.agent-hooks/"
cp -R "$SKILL" "$H/.agents/skills/scope-ledger"
THR=$(jq -r .thread_id "$SKILL/tests/fixtures/scope-ledger.json")
cp "$SKILL/tests/fixtures/scope-ledger.json" "$H/.local/state/agent-quality/scope/$THR.json"
printf '#!/bin/sh\ncat >/dev/null\nexit 0\n' > "$H/.agent-hooks/coordinator-hook.sh"
chmod +x "$H/.agent-hooks/"*.sh
ms() { perl -MTime::HiRes=time -e 'printf "%d", time*1000'; }
bash_payload() { jq -nc --arg c "$1" '{tool_name:"Bash",tool_input:{command:$c},cwd:"/tmp"}'; }
fails=0
# case: <ship stage seconds>|<want rc>|<reason the deny must carry, or ->|<command>
# Past 12 s the scope gate must see the chain clock (HOOK_T0) and decide by
# shape at once ("could not finish"), not start a normal decision.
while IFS='|' read -r slow want why cmd; do
  printf '#!/bin/sh\ncat >/dev/null\nsleep %s\nexit 0\n' "$slow" > "$H/.agent-hooks/qa-ship-gate-hook.sh"
  chmod +x "$H/.agent-hooks/qa-ship-gate-hook.sh"
  a=$(ms)
  bash_payload "$cmd" | HOME="$H" BB_THREAD_ID="$THR" perl -e 'alarm shift; exec @ARGV' "$T" \
    sh "$H/.agent-hooks/coordinator-hook-pretool.sh" >"$H/out" 2>"$H/err"
  rc=$?
  took=$(( $(ms) - a ))
  label="ship stage ${slow}s, [$cmd]"
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
done 2>/dev/null <<'EOF'
0|2|must say|bb thread tell thr_x also refactor it
0|2|must say|bb thr"ead" tell thr_x also refactor it
0|0|-|bb thread tell thr_x serves: P1 next step
0|0|-|ls -la
8|2|must say|bb thread tell thr_x also refactor it
11.8|2|-|bb thread tell thr_x also refactor it
13|2|could not finish|bb thread tell thr_x also refactor it
13|2|could not finish|bb thr"ead" tell thr_x also refactor it
13|0|-|bb thread tell thr_x serves: P1 next step
13|0|-|ls -la
EOF
echo "hook chain test: $([ $fails = 0 ] && echo "all pass" || echo "$fails FAIL") (config $CFG, timeout ${T}s)"
[ $fails = 0 ]
