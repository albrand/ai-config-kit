#!/bin/sh
# Install the shared context-hygiene policy and its Claude Code and Codex adapters.
# Registration is unchanged (Claude: ~/.claude/hooks/context-hygiene.sh, Codex:
# ~/.agent-hooks/codex-context-hygiene.sh), so Codex hook trust is unaffected.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
STAMP=$(date +%Y%m%d%H%M%S)
mkdir -p "$HOME/.agent-hooks" "$HOME/.claude/hooks"
for pair in "context-hygiene-policy.py:$HOME/.agent-hooks/context-hygiene-policy.py" \
            "codex-context-hygiene.sh:$HOME/.agent-hooks/codex-context-hygiene.sh" \
            "claude-context-hygiene.sh:$HOME/.claude/hooks/context-hygiene.sh"; do
  src="$HERE/${pair%%:*}" dst="${pair#*:}"
  [ -f "$dst" ] && cp "$dst" "$dst.bak-$STAMP"
  cp "$src" "$dst"
  chmod +x "$dst"
done
echo "installed context-hygiene policy (backups: *.bak-$STAMP)"
