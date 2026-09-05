# Scope Advisory Skillset

Portable scope-fidelity skill behind the canonical `SCOPE_DISCIPLINE.md`
contract at the repository root.

## Install

Copy the complete package directory, preserving structure — never only
`SKILL.md`, because the skill loads its bundled
`references/SCOPE_DISCIPLINE.md`. `package-manifest.json` is the package
inventory.

- Codex: `codex/scope-advisor/` -> `$CODEX_HOME/skills/scope-advisor/`.
  `CODEX_HOME` is a Codex convention only; no other client uses it.
- Other skills-capable clients: copy into the project skill root the host
  documents — see the Modern Skill-Path Compatibility table in
  `AI_TOOL_ADAPTERS.md` (for example `.agents/skills/scope-advisor/`).
- bb workspaces: `codex/scope-advisor/` -> `<workspace>/.bb/skills/scope-advisor/`.

Validate the source package before copying, from the repository root:

```sh
node scripts/validate-codex-skills.cjs
```

The validator checks the source packages under `skillsets/`; it does not
inspect an installed copy. After copying into bb, confirm native discovery
with `bb skill list --environment <id> --json` and review instruction
injection with `bb guide agent-configuration`.

## Canonical Copy Ownership

The repository-root `SCOPE_DISCIPLINE.md` is canonical. Three bundled copies
must stay byte-identical to it:

- `codex/scope-advisor/references/SCOPE_DISCIPLINE.md`
- `skillsets/core-framework/codex/ai-config-kit-core/references/SCOPE_DISCIPLINE.md`
- `skillsets/adaptive-model-orchestration/codex/adaptive-model-orchestrator/references/SCOPE_DISCIPLINE.md`

The package validator does not enforce this equality. After any edit to the
contract, update all copies together and verify byte equality from the
repository root:

```sh
cmp SCOPE_DISCIPLINE.md skillsets/scope-advisory/codex/scope-advisor/references/SCOPE_DISCIPLINE.md
cmp SCOPE_DISCIPLINE.md skillsets/core-framework/codex/ai-config-kit-core/references/SCOPE_DISCIPLINE.md
cmp SCOPE_DISCIPLINE.md skillsets/adaptive-model-orchestration/codex/adaptive-model-orchestrator/references/SCOPE_DISCIPLINE.md
```

## Evaluation

`evaluation-cases.md` records the behavioral scenarios this contract must
preserve. They are design examples for review, not an executed benchmark; no
evaluation runner is packaged.
