# Skill Library Router Skillset

This skillset keeps large Codex skill libraries accessible without forcing every
skill description into the always-on context budget.

Use it when Codex has many user, system, or plugin skills and the initial skill
list is shortened, omitted, or too noisy to route reliably.

## Entry Points

- Codex skill: `skillsets/skill-library-router/codex/skill-library-router/SKILL.md`
- Codex metadata: `skillsets/skill-library-router/codex/skill-library-router/agents/openai.yaml`
- Codex indexer: `skillsets/skill-library-router/codex/skill-library-router/scripts/refresh-skill-index.cjs`
- Import prompt: `SKILL_LIBRARY_ROUTER_IMPORT_PROMPT.md`

## Operating Model

- Keep `skill-library-router` implicit and lightweight.
- Use the implicit access ladder in the router skill: exact handle, source
  ownership, task verb plus domain, hidden/explicit-only match, then no-skill
  fallback. This keeps skill discovery active even when the user does not name a
  skill explicitly.
- Generate searchable `aliases`, `routingTerms`, and `searchText` for every
  skill. These fields are the router's compact substitute for preloading every
  skill body or description into always-on context.
- Keep specialized or plugin-heavy skills explicit-only when needed to protect
  the initial context budget.
- Keep behavioral framework skills explicit-only when their always-on behavior
  is already encoded in the root directive (`AGENTS.md` / `GLOBAL_AGENTS.md`).
  Preloading their metadata duplicates the directive; the router still surfaces
  the full skill on demand. The indexer's `explicitOnlyUserSkillNames` set lists
  these by default.
- Skip bundled `upstream/` skill copies (the indexer ignores them) so plugins
  that ship an upstream `SKILL.md` alongside their own do not create
  duplicate-named, ambiguous router entries.
- Exclude backup directory trees (names matching `*.bak`, `*.bak.<timestamp>`,
  `*.bak_<ts>`, e.g. `native-agent-surface.bak.20240101T000000Z`) so stale
  installer backups are never indexed. The match is whole-segment only;
  legitimate skill names that merely contain the substring `bak` (e.g.
  `feedback-loop`, `bakery`) are still indexed.
- Index external agent skills (e.g. `~/.agents/skills`, overridable via
  `AGENT_SKILLS_HOME`) with source `agent`. These skills are **vendor
  policy-controlled**: the router reports their existing implicit/explicit mode
  as-is and **never** writes or creates an `agents/openai.yaml` inside them.
  Plugin and existing user/system behavior is unchanged.
- Do not disable skills to save context. Explicit-only skills remain accessible
  by direct `$skill-name` invocation and through the generated index.
- Refresh the index immediately after installing, updating, or removing Codex
  skills or plugins.
- Treat the generated index as local machine state, not a shared framework
  source file.
- Keep host adapters thin. The router chooses and loads the relevant skill; it
  should not copy another skill's full behavior into the global instruction
  layer.

## Validation

After installing the skill into `<CODEX_HOME>/skills/skill-library-router/`, run:

```bash
node <CODEX_HOME>/skills/skill-library-router/scripts/refresh-skill-index.cjs
node <CODEX_HOME>/skills/skill-library-router/scripts/refresh-skill-index.cjs --check
```

Report total skills, implicit skills, explicit-only skills, policy changes, and
any skipped or blocked writes.

An offline selftest (temp fixtures, no real home touched) proves external agent
skills are indexed/source=agent without being written, backup trees are
excluded, and legitimate `bak`-substring names survive:

```bash
node skillsets/skill-library-router/scripts/refresh_skill_index_test.cjs
```
