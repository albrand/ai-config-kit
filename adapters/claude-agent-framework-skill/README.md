# Claude Code Adapter: Always-On Core + Router Skill

This adapter is the **Lightweight Core + Router** install profile from
`FRAMEWORK_MANIFEST.md` — a supported alternative to the eager
`adapters/CLAUDE.md` import list, not a replacement for it. Choose one profile
per repo or tool; do not install both.

It pairs two pieces so an agent always carries the non-negotiables but loads
deeper docs only on demand (progressive disclosure):

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

## Verify

The profile is adopted only when a fresh session can:

1. Name the active install profile (lightweight core + router, not eager
   full-import).
2. State the source-of-truth order from `CORE.md`.
3. List the files it would load for a security review —
   `SECURITY_AND_PENTEST.md` and `skillsets/security-review/README.md`, with the
   authorization gate required before any active testing.
4. List the files it would load for work that leans on an adopted context
   accelerator — `CONTEXT_ACCELERATION.md`,
   `skillsets/context-acceleration/README.md`, and the repo-local operator
   documentation package.

If it cannot route 3 and 4, the install drops contracts the eager adapter loads
eagerly. Fix the skill's task map before relying on it.

Re-run the router coverage check from `FRAMEWORK_MANIFEST.md` whenever framework
files are added, removed, or renamed.

## Why

Bootstrap prompts that load the whole framework cost tokens on every turn. A tiny
always-on core plus an on-demand router keeps the non-negotiables in context
cheaply, and pulls depth only when a task actually needs it.
