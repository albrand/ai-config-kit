#!/bin/sh
# install-scope-gate.sh into a throwaway HOME, then the hook protocol end to end (review of #92,
# round 7): the Claude PostToolUse matcher and the Codex registration and trust are what the
# installer wrote; eight spawns through the INSTALLED PreToolUse gate pass, and the INSTALLED
# gap-map hook then prints the note and exits 0. Host integration: the installer's selftest reads
# the running bb's help, so this runs on a host with bb, not in the checkout-only suite.
set -eu
# The installer runs codex-hook-trust.py, which reads config.toml with tomllib (Python 3.11+). The
# hooks it installs run on older Pythons too; test-gap-map-hook.sh covers those.
python3 -c 'import tomllib' 2>/dev/null || { echo "FAIL install-scope-gate.sh needs Python 3.11+ (tomllib); this is $(python3 --version 2>&1)"; exit 1; }
KIT="$(cd "$(dirname "$0")/../../.." && pwd)"
T="$(mktemp -d "${TMPDIR:-/tmp}/gap-map-install.XXXXXX")"  # macOS mktemp ignores TMPDIR without a template
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/.claude" "$T/.codex" "$T/.agents/skills" "$T/.bb/skills" "$T/.claude/skills" "$T/.codex/skills" "$T/.agent-hooks"
cat > "$T/.claude/settings.json" <<EOF
{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "$T/.agent-hooks/coordinator-hook-pretool.sh", "timeout": 15}]}]}}
EOF
cat > "$T/.codex/hooks.json" <<EOF
{"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "$T/.agent-hooks/coordinator-hook-pretool.sh", "timeout": 15}]}]}}
EOF
: > "$T/.codex/config.toml"
fail=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: got [$2] want [$3]"; fail=1; fi; }

HOME="$T" sh "$KIT/skillsets/qa-enforcement/hooks/install-scope-gate.sh" > "$T/install.log" 2>&1 || { cat "$T/install.log"; echo "FAIL installer exited non-zero"; exit 1; }
check "installer: gap-map hook installed and executable" "$([ -x "$T/.agent-hooks/gap-map-hook.sh" ] && echo yes)" "yes"
for h in .agents .bb .claude .codex; do
  check "installer: scope-ledger in ~/$h/skills has the nudge" "$(grep -c 'def gap_map_nudge' "$T/$h/skills/scope-ledger/scripts/scope-gate.py")" "1"
done
claude=$(python3 - "$T" <<'EOF'
import json, sys
t = sys.argv[1]
d = json.load(open(t + "/.claude/settings.json"))
m = [e.get("matcher", "") for e in d["hooks"].get("PostToolUse", [])
     if any(h["command"] == t + "/.agent-hooks/gap-map-hook.sh" for h in e["hooks"])]
need = ["Bash", "mcp__bb-bridge__fleet_member_spawn", "mcp__bb-bridge__fleet_member_tell"]
print("ok" if len(m) == 1 and all(n in m[0].split("|") for n in need) else m)
EOF
)
check "Claude: one PostToolUse entry, matcher covers Bash and the bb dispatch tools" "$claude" "ok"
codex=$(python3 - "$T" <<'EOF'
import json, sys
t = sys.argv[1]
d = json.load(open(t + "/.codex/hooks.json"))
print(sum(1 for e in d["hooks"].get("PostToolUse", []) for h in e["hooks"] if h["command"] == t + "/.agent-hooks/gap-map-hook.sh"))
EOF
)
check "Codex: one PostToolUse registration" "$codex" "1"
HOME="$T" python3 "$KIT/skillsets/qa-enforcement/hooks/codex-hook-trust.py" --check --only-command "$T/.agent-hooks/gap-map-hook.sh" --only-event PostToolUse > "$T/trust.log" 2>&1 && trusted=yes || trusted=no
check "Codex: the registration is trusted (an untrusted hook is skipped silently)" "$trusted" "yes"
HOME="$T" sh "$KIT/skillsets/qa-enforcement/hooks/install-scope-gate.sh" > "$T/install2.log" 2>&1
check "installer twice: still one Claude entry" "$(grep -o 'gap-map-hook.sh' "$T/.claude/settings.json" | wc -l | tr -d ' ')" "1"

# The hook protocol with the installed copies: a coordinator with a ledger spawns eight children.
TID=thr_gapmapinstall
mkdir -p "$T/.local/state/agent-quality/scope"
python3 - "$KIT/skillsets/qa-enforcement/shared/scope-ledger/tests/fixtures/scope-ledger.json" "$T/.local/state/agent-quality/scope/$TID.json" "$TID" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1])); d["thread_id"] = sys.argv[3]
for p in d["purposes"]:
    p["status"] = "open"
json.dump(d, open(sys.argv[2], "w"))
EOF
payload='{"tool_name": "Bash", "tool_input": {"command": "bb thread spawn --parent-self --prompt \"serves: P1\\nmap the gap\""}}'
pre=0; i=0
while [ $i -lt 8 ]; do
  printf '%s' "$payload" | HOME="$T" BB_THREAD_ID=$TID sh "$T/.agent-hooks/scope-gate-hook.sh" >/dev/null 2>&1 || pre=$?
  i=$((i + 1))
done
check "installed PreToolUse gate: 8 spawns serving P1 pass" "$pre" "0"
out=$(printf '%s' "$payload" | HOME="$T" BB_THREAD_ID=$TID sh "$T/.agent-hooks/gap-map-hook.sh"); rc=$?
check "installed PostToolUse hook: exits 0" "$rc" "0"
note=$(printf '%s' "$out" | python3 -c 'import json, sys
o = json.load(sys.stdin)["hookSpecificOutput"]
print("ok" if o["hookEventName"] == "PostToolUse" and "8 dispatches" in o["additionalContext"] else o)' 2>&1)
check "installed PostToolUse hook: prints the note as additionalContext" "$note" "ok"
[ $fail -eq 0 ] && echo "gap-map install: all pass" || { echo "gap-map install: FAIL"; exit 1; }
