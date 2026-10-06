#!/bin/sh
# Install the verify skill and its PostToolUse hook. Run from the kit checkout:
#   sh skillsets/repo-bootstrap/install.sh
# - copies shared/verify into the four skill homes (identical copies)
# - installs ~/.agent-hooks/verify-hook.sh and registers it for Claude Code and Codex
# - records Codex trust for that one command (Codex skips untrusted hooks silently)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
for h in "$HOME/.agents/skills" "$HOME/.bb/skills" "$HOME/.claude/skills" "$HOME/.codex/skills"; do
  [ -d "$h" ] || continue
  rm -rf "$h/verify"
  cp -R "$HERE/shared/verify" "$h/verify"
  find "$h/verify" -name __pycache__ -type d -prune -exec rm -rf {} +
done
mkdir -p "$HOME/.agent-hooks"
cp "$HERE/hooks/verify-hook.sh" "$HOME/.agent-hooks/verify-hook.sh"
chmod +x "$HOME/.agent-hooks/verify-hook.sh"
python3 "$HERE/hooks/register_verify_hook.py"
TRUST="$HOME/.agent-hooks/codex-hook-trust.py"
if [ -f "$HOME/.codex/hooks.json" ] && [ -f "$TRUST" ]; then
  python3 "$TRUST" --trust --only-command "$HOME/.agent-hooks/verify-hook.sh" --only-event PostToolUse
fi
echo "installed verify skill and hook"
