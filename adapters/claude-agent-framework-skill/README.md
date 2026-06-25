# Claude Code Adapter: Always-On Core + Router Skill

This adapter pairs two pieces so an agent always carries the non-negotiables but
loads deeper docs only on demand (progressive disclosure):

1. **`CORE.md`** (repo root) — a small always-on distillation imported into every
   session via the Claude Code instruction file.
2. **This router skill** — maps a task to the exact deeper framework file(s) so
   the agent Reads only what the work needs instead of force-loading everything.

## Install

1. Import the core into your Claude Code instructions (`CLAUDE.md` at user or
   repo level):

   ```md
   @path/to/CORE.md
   ```

2. Install this skill so it is discoverable:

   ```text
   ~/.claude/skills/agent-framework/SKILL.md      # user level
   .claude/skills/agent-framework/SKILL.md         # repo level
   ```

3. Point the skill's "Files live in ..." line and the task→file map at wherever
   the framework docs are installed (the kit's recommended path is
   `docs/agent-framework/`).

## Why

Bootstrap prompts that load the whole framework cost tokens on every turn. A tiny
always-on core plus an on-demand router keeps the non-negotiables in context
cheaply, and pulls depth only when a task actually needs it.
