# Skill Library Router Import Prompt

Use this prompt when a user wants an AI assistant to import or update the Codex
Skill Library Router from this config kit.

Canonical source repository: `https://github.com/albrand/ai-config-kit`

This prompt is intentionally generic. Do not add private repository names,
private URLs, secrets, credentials, account IDs, or closed-scope operational
details.

## Prompt

```text
You are helping me import the Skill Library Router from the Agent Configuration Framework into Codex.

Canonical source repository:
- `https://github.com/albrand/ai-config-kit`

Goal:
- Install or update the Codex `skill-library-router` skill.
- Keep all installed skills accessible when needed.
- Reduce always-on skill metadata by routing specialized skills through a generated local index instead of disabling them.
- Support implicit skill access from task language through generated aliases,
  routing terms, and search text; the user should not need to name the skill
  explicitly when the task clearly maps to one.
- Refresh the skill index immediately after install and after any future skill or plugin add, update, or removal.
- Preserve local customizations and avoid overwriting target files silently.
- Verify the installed files and generated index before claiming completion.

Source of truth:
- First use the attached, pasted, current, or archived `agent-config-kit` contents when I provide them.
- If no local source package is attached or readable, fetch or clone `https://github.com/albrand/ai-config-kit` if network and git access are available.
- If you cannot access the repository and I did not provide the package, stop and ask me to attach the repo, paste the files, or provide a readable checkout path.
- Required source files:
  - `skillsets/skill-library-router/README.md`
  - `skillsets/skill-library-router/codex/skill-library-router/SKILL.md`
  - `skillsets/skill-library-router/codex/skill-library-router/agents/openai.yaml`
  - `skillsets/skill-library-router/codex/skill-library-router/scripts/refresh-skill-index.cjs`
- Helpful framework files, when available:
  - `AI_TOOL_ADAPTERS.md`
  - `FRAMEWORK_MANIFEST.md`
  - `CONFIG_KIT_AI_PROMPT.md`
  - `SKILLS_CATALOG.md`

Before editing:
1. Confirm which source package or folder you are reading.
2. Determine `<CODEX_HOME>`.
   - Use the `CODEX_HOME` environment variable if present.
   - Otherwise use `~/.codex` as the default user-level path.
3. Inspect existing target files before overwriting them.
4. If an existing target file differs from the source, summarize the difference and ask before replacing it.
5. Do not change unrelated files.

Codex import:
1. Create `<CODEX_HOME>/skills/skill-library-router/`.
2. Copy:
   - `skillsets/skill-library-router/codex/skill-library-router/SKILL.md`
     to `<CODEX_HOME>/skills/skill-library-router/SKILL.md`
   - `skillsets/skill-library-router/codex/skill-library-router/agents/openai.yaml`
     to `<CODEX_HOME>/skills/skill-library-router/agents/openai.yaml`
   - `skillsets/skill-library-router/codex/skill-library-router/scripts/refresh-skill-index.cjs`
     to `<CODEX_HOME>/skills/skill-library-router/scripts/refresh-skill-index.cjs`
3. If the active Codex runtime does not support UI metadata, still copy `openai.yaml` when the file can live beside the skill, but report that UI metadata support was not verified.

Mandatory index refresh:
1. Run:
   `node <CODEX_HOME>/skills/skill-library-router/scripts/refresh-skill-index.cjs`
2. Then run:
   `node <CODEX_HOME>/skills/skill-library-router/scripts/refresh-skill-index.cjs --check`
3. Confirm these generated files exist:
   - `<CODEX_HOME>/skills/skill-library-router/references/skill-index.json`
   - `<CODEX_HOME>/skills/skill-library-router/references/skill-index.md`
   - `<CODEX_HOME>/skills/skill-library-router/references/applied-policy-summary.json`
4. Report total skills, implicit skills, explicit-only skills, and policy changes.
5. If the indexer cannot write because the assistant is sandboxed, request the smallest permission needed to write to `<CODEX_HOME>`, or give me the exact local command to run.

Policy:
- Do not disable skills to save context.
- Keep `skill-library-router` implicit.
- Keep specialized or plugin-heavy skills explicit-only when needed.
- Keep behavioral framework skills explicit-only when their always-on behavior already lives in the root directive (AGENTS.md / GLOBAL_AGENTS.md); the indexer lists these in `explicitOnlyUserSkillNames` and the router still surfaces them on demand.
- The indexer skips bundled `upstream/` skill copies so plugins that ship an upstream SKILL.md beside their own do not create duplicate-named router entries.
- The generated index includes `aliases`, `routingTerms`, and `searchText` so
  the router can load hidden or explicit-only skills from task language rather
  than only from direct `$skill-name` mentions.
- Treat explicit-only as router-accessible, not unavailable.
- Re-run the index refresh whenever skills or plugins are installed, updated, or removed.

Verification:
1. List every installed or updated target file.
2. Compare each installed file against the source file, using byte-for-byte comparison when the environment supports it.
3. Report existing files that were left unchanged, replaced, or skipped.
4. Report missing source files, missing permissions, unavailable tool support, or skipped verification separately.
5. Confirm no unrelated files were changed.

After import, give me this try-it prompt:
- Codex: `Use $skill-library-router to find the right skill for this task, then load only that skill's SKILL.md and required references.`

Safety rules:
- Do not include secrets or credentials in copied files, prompts, logs, or summaries.
- Do not mutate repositories, cloud resources, trackers, secrets, or MCP registrations during import verification.
- Do not push repository changes unless I explicitly ask you to push.
- If verification fails or access is blocked, stop and report the exact blocker plus the smallest safe next step.
```

## Compact Prompt

Use this when the assistant already has the config kit loaded:

```text
Import the Skill Library Router from `https://github.com/albrand/ai-config-kit` or from the attached/readable local config-kit package if I provided one. Install the Codex skill from `skillsets/skill-library-router/codex/skill-library-router/` into `<CODEX_HOME or ~/.codex>/skills/skill-library-router/`, including `SKILL.md`, `agents/openai.yaml`, and `scripts/refresh-skill-index.cjs`. Inspect existing targets before overwriting, ask before replacing customized files, run `node <CODEX_HOME>/skills/skill-library-router/scripts/refresh-skill-index.cjs`, then run the same command with `--check`, verify generated `references/skill-index.json`, `skill-index.md`, and `applied-policy-summary.json`, report counts and policy changes, and do not disable skills, mutate unrelated files, or touch repositories, cloud resources, trackers, secrets, or MCP registrations during import.
```
