---
name: skill-library-router
description: Find and load the right Codex skill from a large local library when skill descriptions are shortened, hidden, explicit-only, or no visible skill clearly matches. Use before giving up on skill context, after skill or plugin library changes, or when Codex needs smart access to all installed skills without injecting every skill description into the initial context.
---

# Skill Library Router

Use this skill as the always-on routing shim for large Codex skill libraries.

## Workflow

1. Read `references/skill-index.json` first. If it is missing or stale, run
   `scripts/refresh-skill-index.cjs` before routing.
2. Normalize the user's task into direct handles (`$skill`, `@plugin`,
   `/command`), domain nouns, action verbs, tool names, repo names, and lifecycle
   hints such as "review", "debug", "deploy", "design", "browser", "figma",
   "spreadsheet", or "workflow".
3. Match those terms against each indexed skill's `name`, `aliases`,
   `routingTerms`, `searchText`, `description`, `source`, `plugin`, and `path`
   fields.
4. Do not require the user to name a skill. If task language maps to an indexed
   hidden or explicit-only skill, load that skill directly.
5. Prefer an exact explicit mention such as `$skill-name` or `@plugin-name` when
   present.
6. If no visible skill matches, search the index with likely task nouns and
   verbs before proceeding without a skill.
7. Open the selected skill's `SKILL.md` directly from its indexed `path` and
   follow it as if it had been selected normally.
8. Load referenced files from that skill only when the selected skill says they
   are needed.
9. If the selected skill requires MCP or another external tool, apply the active
   MCP routing rules before using that tool.

## Implicit Access Ladder

Stop at the first rung that holds:

1. Exact handle: `$skill`, `@plugin`, slash command, or skill name.
2. Source ownership: task names a platform or plugin whose indexed skill owns the
   answer, such as Vercel, Figma, Browser, MongoDB, OpenAI docs, presentations,
   spreadsheets, or documents.
3. Task verb plus domain: examples include "review this PR",
   "debug failing tests", "open localhost", "create a deck", "build a
   workflow", "update Next.js", or "design this screen".
4. Hidden/explicit-only match: the best indexed `routingTerms` or `searchText`
   match is a skill whose metadata was excluded from always-on context.
5. No match: proceed without a skill and say the local router had no useful hit
   only when that matters to the outcome.

This ladder is a routing reflex, not a research project. Load the narrowest
matching skill, then let that skill's own instructions control depth.

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
- Prefer indexed aliases and trigger terms over ad hoc guessing when the user
  did not explicitly name a skill.
- Keep adapters thin: the router selects and loads skills; it does not copy
  another skill's full behavior into always-on context.
- If multiple skills match and the choice changes behavior, state the fallback
  candidate and why it was not selected.

## Output

When routing matters, report:

- Selected skill and why it matched.
- Any missing or stale index state.
- Any skill files that could not be read.
- Whether a fallback was used.
