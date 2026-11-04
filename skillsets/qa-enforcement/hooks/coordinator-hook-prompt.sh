#!/bin/sh
# prompt adapter for coordinator-mode (no argv: Codex runs hook commands as a path)
exec "$HOME/.agent-hooks/coordinator-hook.sh" prompt
