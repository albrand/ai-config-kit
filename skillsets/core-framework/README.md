# Core Framework Codex Skill

Self-contained, explicit-only Codex entrypoint for loading the narrowest
ai-config-kit profile that applies to a task.

Install by copying the complete
`codex/ai-config-kit-core/` directory to
`<CODEX_HOME>/skills/ai-config-kit-core/`. Preserve the package manifest and all
bundled references. Validate from the repository root with:

```sh
node scripts/validate-codex-skills.cjs
```

Refresh the Skill Library Router index after installing or updating the skill.
