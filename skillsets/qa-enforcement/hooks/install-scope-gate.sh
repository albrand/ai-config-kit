#!/bin/sh
# Install/update the scope gate from this kit checkout. Touches only scope
# pieces: it does not reinstall qa-sweep (install.sh owns that).
# - scope-ledger skill into all four skill homes (identical copies)
# - ~/.agent-hooks/scope-gate-hook.sh and the chained coordinator-hook-pretool.sh
# - adds mcp__bb-bridge__fleet_member_tell to the Claude PreToolUse matcher that
#   runs coordinator-hook-pretool.sh (Codex runs it for every tool already)
# Replaced files are backed up to ~/.agent-hooks/backups/scope-gate-<date>/.
set -eu
KIT="$(cd "$(dirname "$0")/../../.." && pwd)"
SRC="$KIT/skillsets/qa-enforcement"
BK="$HOME/.agent-hooks/backups/scope-gate-$(date +%Y-%m-%d)"
mkdir -p "$BK"
python3 "$SRC/shared/scope-ledger/scripts/scope-gate.py" selftest >/dev/null 2>&1
# 1. skill into four homes
for h in "$HOME/.agents/skills" "$HOME/.bb/skills" "$HOME/.claude/skills" "$HOME/.codex/skills"; do
  rm -rf "$h/scope-ledger"
  cp -R "$SRC/shared/scope-ledger" "$h/scope-ledger"
done
# 2. hook wrappers (backup first)
for f in coordinator-hook-pretool.sh scope-gate-hook.sh; do
  [ -f "$HOME/.agent-hooks/$f" ] && cp -p "$HOME/.agent-hooks/$f" "$BK/$f"
  cp "$SRC/hooks/$f" "$HOME/.agent-hooks/$f"
  chmod +x "$HOME/.agent-hooks/$f"
done
# 3. Claude matcher: fleet_member_tell reaches the gate too
S="$HOME/.claude/settings.json"
TELL="mcp__bb-bridge__fleet_member_tell"
if jq -e --arg t "$TELL" '[.hooks.PreToolUse[]? | select(any(.hooks[]?; .command | endswith("coordinator-hook-pretool.sh"))) | .matcher | split("|") | index($t)] | all(. != null)' "$S" >/dev/null; then
  echo "claude matcher already has $TELL"
else
  cp -p "$S" "$BK/claude-settings.json"
  tmp="$(mktemp "$HOME/.claude/.settings.XXXXXX")"
  jq --arg t "$TELL" '.hooks.PreToolUse |= map(if any(.hooks[]?; .command | endswith("coordinator-hook-pretool.sh")) then .matcher = (.matcher + "|" + $t) else . end)' "$S" > "$tmp"
  chmod 644 "$tmp"
  mv "$tmp" "$S"
  # Nothing but the PreToolUse matchers may differ from the backup.
  jq -S 'del(.hooks.PreToolUse)' "$BK/claude-settings.json" > "$BK/.before"
  jq -S 'del(.hooks.PreToolUse)' "$S" > "$BK/.after"
  diff "$BK/.before" "$BK/.after" >/dev/null
  rm -f "$BK/.before" "$BK/.after"
  echo "claude matcher: added $TELL (settings backup: $BK/claude-settings.json)"
fi
# 4. host timeout on the chain entry: at least the gates' HOOK_HOST_TIMEOUT_S
#    (a timed-out PreToolUse hook lets the command run; backup inside)
python3 "$SRC/hooks/hook-timeouts.py" apply
echo "installed scope gate; backup: $BK"

