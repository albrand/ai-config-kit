#!/bin/sh
# Install only the Pallium real-data replay gate, preserving installed QA gates.
set -eu
KIT="$(cd "$(dirname "$0")/../../.." && pwd)"
QA="$KIT/skillsets/qa-enforcement/shared/qa-sweep"
STAMP="$(date +%Y%m%dT%H%M%S)"
BK="$HOME/.agent-hooks/backups/realdata-replay-$STAMP"
mkdir -p "$BK"

atomic_copy() {
  source="$1"
  target="$2"
  mode="${3:-755}"
  mkdir -p "$(dirname "$target")"
  temp="$target.new.$$"
  cp "$source" "$temp"
  chmod "$mode" "$temp"
  mv "$temp" "$target"
}

# Keep all prior copies so this targeted install can be rolled back exactly.
for h in "$HOME/.agents/skills" "$HOME/.bb/skills" "$HOME/.claude/skills" "$HOME/.codex/skills"; do
  provider="$(basename "$(dirname "$h")")"
  paths_target="$h/qa-sweep/realdata-paths.json"
  gate_target="$h/qa-sweep/scripts/realdata-replay-gate.py"
  [ ! -f "$paths_target" ] || cp -p "$paths_target" "$BK/$provider-realdata-paths.json"
  [ ! -f "$gate_target" ] || cp -p "$gate_target" "$BK/$provider-realdata-replay-gate.py"
  atomic_copy "$QA/realdata-paths.json" "$paths_target" 644
  atomic_copy "$QA/scripts/realdata-replay-gate.py" "$gate_target"
  dest="$h/pr-review/scripts/pre-review.py"
  [ ! -f "$dest" ] || cp -p "$dest" "$BK/pre-review-$provider.py"
  atomic_copy "$KIT/scripts/pre-review.py" "$dest"
done

hook="$HOME/.agent-hooks/qa-ship-gate-hook.sh"
[ ! -f "$hook" ] || cp -p "$hook" "$BK/qa-ship-gate-hook.sh"
atomic_copy "$KIT/skillsets/qa-enforcement/hooks/qa-ship-gate-hook.sh" "$hook"

echo "installed targeted real-data replay gate; backup: $BK"
