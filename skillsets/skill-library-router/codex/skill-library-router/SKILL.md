---
name: skill-library-router
description: Find and load the right Codex skill from a large local library when skill descriptions are shortened, hidden, explicit-only, or no visible skill clearly matches. Use before giving up on skill context, after skill or plugin library changes, or when Codex needs smart access to all installed skills without injecting every skill description into the initial context.
---

# Skill Library Router

Use this skill as the always-on routing shim for large Codex skill libraries.

## Workflow

1. Read `references/skill-index.json` first. If it is missing or stale, run
   `scripts/refresh-skill-index.cjs` before routing.
2. Match the user task against skill `name`, `description`, `source`, `plugin`,
   and `path` fields.
3. Prefer an exact explicit mention such as `$skill-name` or `@plugin-name` when
   present.
4. If no visible skill matches, search the index with likely task nouns and
   verbs before proceeding without a skill.
5. Open the selected skill's `SKILL.md` directly from its indexed `path` and
   follow it as if it had been selected normally.
6. Load referenced files from that skill only when the selected skill says they
   are needed.
7. If the selected skill requires MCP or another external tool, apply the active
   MCP routing rules before using that tool.

## Refresh

Run this after installing, removing, or updating Codex skills or plugins:

```bash
node <CODEX_HOME>/skills/skill-library-router/scripts/refresh-skill-index.cjs
```

If `CODEX_HOME` is unset, the script uses `~/.codex`.

To verify that the generated index matches the current skill library without
writing files:

```bash
node <CODEX_HOME>/skills/skill-library-router/scripts/refresh-skill-index.cjs --check
```

## Selection Rules

- Keep the router active and lightweight.
- Do not bulk-read all skill bodies.
- Do not treat explicit-only skills as disabled; they remain available through
  this index and direct `$skill-name` invocation.
- Prefer the narrowest matching skill first.
- If multiple skills match and the choice changes behavior, state the fallback
  candidate and why it was not selected.

## Output

When routing matters, report:

- Selected skill and why it matched.
- Any missing or stale index state.
- Any skill files that could not be read.
- Whether a fallback was used.
