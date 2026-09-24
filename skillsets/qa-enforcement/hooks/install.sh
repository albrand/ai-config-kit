#!/bin/sh
# Install/update the QA ship gate (run from the kit: scripts are staged in /tmp/qa-card2).
# - backs up replaced files to ~/.agent-hooks/backups/qa-ship-gate-2026-09-24/
# - installs ~/.agent-hooks wrappers, rewrites coordinator-hook-pretool.sh,
#   wires the Stop hook into ~/.claude/settings.json and ~/.codex/hooks.json,
#   copies the qa-sweep skill into all four skill homes
set -eu
STAGE="${1:?staging dir}"
BK="$HOME/.agent-hooks/backups/qa-ship-gate-2026-09-24"
mkdir -p "$BK"
# 1. skill into four homes (identical copies; skill-drift-check compares them)
for h in "$HOME/.agents/skills" "$HOME/.bb/skills" "$HOME/.claude/skills" "$HOME/.codex/skills"; do
  rm -rf "$h/qa-sweep"
  cp -R "$STAGE/qa-sweep" "$h/qa-sweep"
done
# 2. agent-hooks wrappers
cp "$STAGE/hooks/qa-ship-gate-hook.sh" "$HOME/.agent-hooks/qa-ship-gate-hook.sh"
cp "$STAGE/hooks/qa-stop-hook.sh" "$HOME/.agent-hooks/qa-stop-hook.sh"
# 3. coordinator pretool adapter (backup first)
[ -f "$HOME/.agent-hooks/coordinator-hook-pretool.sh" ] && cp "$HOME/.agent-hooks/coordinator-hook-pretool.sh" "$BK/"
cp "$STAGE/hooks/coordinator-hook-pretool.sh" "$HOME/.agent-hooks/coordinator-hook-pretool.sh"
chmod +x "$HOME/.agent-hooks/qa-ship-gate-hook.sh" "$HOME/.agent-hooks/qa-stop-hook.sh" \
         "$HOME/.agent-hooks/coordinator-hook-pretool.sh"
echo "installed hooks; backup: $BK"
