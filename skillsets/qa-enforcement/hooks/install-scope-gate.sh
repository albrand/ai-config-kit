#!/bin/sh
# Install/update the scope gate from this kit checkout. Touches only scope
# pieces: it does not reinstall qa-sweep (install.sh owns that).
# - scope-ledger skill into all four skill homes (identical copies)
# - ~/.agent-hooks/scope-gate-hook.sh and the chained coordinator-hook-pretool.sh
# - adds every gated agent tool (scope-gate.py MCP_FIELDS) to the Claude
#   PreToolUse matcher that runs coordinator-hook-pretool.sh (Codex runs it
#   for every tool already)
# Replaced files are backed up to ~/.agent-hooks/backups/scope-gate-<date>/.
set -eu
KIT="$(cd "$(dirname "$0")/../../.." && pwd)"
SRC="$KIT/skillsets/qa-enforcement"
BK="$HOME/.agent-hooks/backups/scope-gate-$(date +%Y-%m-%d)"
mkdir -p "$BK"
python3 "$SRC/shared/scope-ledger/scripts/scope-gate.py" selftest >/dev/null 2>&1
# Hooks fire on every agent's tool call while this runs, so nothing is copied
# over a live file: a copy is staged beside it and renamed into place. A hook
# that reads mid-install sees the old file or the new one, never part of one.
# 1. skill into four homes (between the two renames the skill is absent for a
#    moment; the wrapper then decides by shape, which fails closed)
for h in "$HOME/.agents/skills" "$HOME/.bb/skills" "$HOME/.claude/skills" "$HOME/.codex/skills"; do
  rm -rf "$h/scope-ledger.new" "$h/scope-ledger.old"
  cp -R "$SRC/shared/scope-ledger" "$h/scope-ledger.new"
  find "$h/scope-ledger.new" -name __pycache__ -type d -prune -exec rm -rf {} +
  [ -d "$h/scope-ledger" ] && mv "$h/scope-ledger" "$h/scope-ledger.old"
  mv "$h/scope-ledger.new" "$h/scope-ledger"
  rm -rf "$h/scope-ledger.old"
done
# 2. hook wrappers (backup first)
for f in coordinator-hook-pretool.sh scope-gate-hook.sh; do
  [ -f "$HOME/.agent-hooks/$f" ] && cp -p "$HOME/.agent-hooks/$f" "$BK/$f"
  cp "$SRC/hooks/$f" "$HOME/.agent-hooks/$f.new"
  chmod +x "$HOME/.agent-hooks/$f.new"
  mv "$HOME/.agent-hooks/$f.new" "$HOME/.agent-hooks/$f"
done
# 3. Claude matcher: every gated agent tool reaches the gate (review r2b D6:
#    the task, advise and context tools were not routed to it at all)
S="$HOME/.claude/settings.json"
TOOLS=$(python3 -c 'import importlib.util, sys
spec = importlib.util.spec_from_file_location("sg", sys.argv[1]); sg = importlib.util.module_from_spec(spec); spec.loader.exec_module(sg)
print(" ".join("mcp__bb-bridge__" + t for t in sg.MCP_FIELDS))' "$SRC/shared/scope-ledger/scripts/scope-gate.py")
[ -n "$TOOLS" ] || { echo "no gated tool list from scope-gate.py" >&2; exit 1; }
before="$(mktemp "$HOME/.claude/.settings-before.XXXXXX")"
cp -p "$S" "$before"
added=""
for t in $TOOLS; do
  if ! jq -e --arg t "$t" '[.hooks.PreToolUse[]? | select(any(.hooks[]?; .command | endswith("coordinator-hook-pretool.sh"))) | .matcher | split("|") | index($t)] | all(. != null)' "$S" >/dev/null; then
    tmp="$(mktemp "$HOME/.claude/.settings.XXXXXX")"
    jq --arg t "$t" '.hooks.PreToolUse |= map(if any(.hooks[]?; .command | endswith("coordinator-hook-pretool.sh")) and (.matcher | split("|") | index($t)) == null then .matcher = (.matcher + "|" + $t) else . end)' "$S" > "$tmp"
    chmod 644 "$tmp"
    mv "$tmp" "$S"
    added="$added $t"
  fi
done
# Nothing but the PreToolUse matchers may differ from the backup.
jq -S 'del(.hooks.PreToolUse)' "$before" > "$BK/.before"
jq -S 'del(.hooks.PreToolUse)' "$S" > "$BK/.after"
diff "$BK/.before" "$BK/.after" >/dev/null
rm -f "$BK/.before" "$BK/.after"
if [ -n "$added" ]; then
  mv "$before" "$BK/claude-settings.$(date +%H%M%S).json"
  echo "claude matcher: added$added (settings backup in $BK)"
else
  rm -f "$before"
  echo "claude matcher already has every gated tool"
fi
# 4. host timeout on the chain entry: at least the gates' HOOK_HOST_TIMEOUT_S
#    (a timed-out PreToolUse hook lets the command run; backup inside)
python3 "$SRC/hooks/hook-timeouts.py" apply
echo "installed scope gate; backup: $BK"

