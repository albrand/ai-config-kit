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
- Keep specialized or plugin-heavy skills explicit-only when needed to protect
  the initial context budget.
- Do not disable skills to save context. Explicit-only skills remain accessible
  by direct `$skill-name` invocation and through the generated index.
- Refresh the index immediately after installing, updating, or removing Codex
  skills or plugins.
- Treat the generated index as local machine state, not a shared framework
  source file.

## Validation

After installing the skill into `<CODEX_HOME>/skills/skill-library-router/`, run:

```bash
node <CODEX_HOME>/skills/skill-library-router/scripts/refresh-skill-index.cjs
node <CODEX_HOME>/skills/skill-library-router/scripts/refresh-skill-index.cjs --check
```

Report total skills, implicit skills, explicit-only skills, policy changes, and
any skipped or blocked writes.
