#!/bin/sh
# Stop-hook adapter for the QA sweep (Claude Code + Codex). Reads the Stop
# payload on stdin. Blocks the turn from ending while .qa/inventory.jsonl has
# open rows, only inside .qa-opted-in repos. Honours stop_hook_active.
exec python3 "$HOME/.agents/skills/qa-sweep/scripts/ship-gate.py" stop
