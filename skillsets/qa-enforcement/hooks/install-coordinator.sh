#!/bin/sh
# Install coordinator-mode and spawn-route hooks into ~/.agent-hooks.
# Does not touch coordinator-hook-pretool.sh (install-scope-gate.sh owns that).
# Replaced files are backed up to ~/.agent-hooks/backups/coordinator-<date>/.
set -eu
KIT="$(cd "$(dirname "$0")/../../.." && pwd)"
SRC="$KIT/skillsets/qa-enforcement/hooks"
BK="$HOME/.agent-hooks/backups/coordinator-$(date +%Y-%m-%d)"
mkdir -p "$BK" "$HOME/.agent-hooks"
install_one() {
  f=$1
  exec_flag=$2
  [ -f "$HOME/.agent-hooks/$f" ] && cp -p "$HOME/.agent-hooks/$f" "$BK/$f"
  cp "$SRC/$f" "$HOME/.agent-hooks/$f.new"
  if [ "$exec_flag" = x ]; then
    chmod +x "$HOME/.agent-hooks/$f.new"
  else
    chmod 644 "$HOME/.agent-hooks/$f.new"
  fi
  mv "$HOME/.agent-hooks/$f.new" "$HOME/.agent-hooks/$f"
}
for f in coordinator-hook.sh coordinator-hook-prompt.sh coordinator-mode.py spawn-route.py; do
  install_one "$f" x
done
install_one spawn-route.mode ""
echo "installed coordinator and spawn-route hooks; backup: $BK"
