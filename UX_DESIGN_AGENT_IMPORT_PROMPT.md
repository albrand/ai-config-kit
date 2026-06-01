# UX Design Agent Import Prompt

Use this prompt when a user wants an AI assistant to import the UX Design Agent skillset from this config kit into Codex and Claude Code.

Canonical source repository: `https://github.com/albrand/ai-config-kit`

This prompt is intentionally generic. Do not add private repository names, private URLs, secrets, credentials, account IDs, or closed-scope operational details.

## Prompt

```text
You are helping me import the UX Design Agent skillset from the Agent Configuration Framework into my AI tools.

Canonical source repository:
- `https://github.com/albrand/ai-config-kit`

Goal:
- Install or update the Codex `ux-design-agent` skill.
- Install or update the Claude Code `/ux-design-agent` command.
- Preserve local customizations and avoid overwriting target files silently.
- Verify the installed files before claiming completion.

Source of truth:
- First use the attached, pasted, current, or archived `agent-config-kit` contents when I provide them.
- If no local source package is attached or readable, fetch or clone `https://github.com/albrand/ai-config-kit` if network and git access are available.
- If you cannot access the repository and I did not provide the package, stop and ask me to attach the repo, paste the files, or provide a readable checkout path.
- Required source files:
  - `skillsets/ux-design-agent/README.md`
  - `skillsets/ux-design-agent/references/output-contract.md`
  - `skillsets/ux-design-agent/codex/ux-design-agent/SKILL.md`
  - `skillsets/ux-design-agent/codex/ux-design-agent/references/output-contract.md`
  - `skillsets/ux-design-agent/codex/ux-design-agent/agents/openai.yaml`
  - `skillsets/ux-design-agent/claude/commands/ux-design-agent.md`
- Helpful framework files, when available:
  - `AI_TOOL_ADAPTERS.md`
  - `FRAMEWORK_MANIFEST.md`
  - `CONFIG_KIT_AI_PROMPT.md`

Before editing:
1. Confirm which source package or folder you are reading.
2. Confirm whether the install target is user-level, project-level, or both.
   - Recommended default: user-level for personal tools.
   - Recommended default: project-level only when a team wants the command versioned with a repo.
3. If the target scope is unclear, ask one direct question before copying files.
4. Inspect existing target files before overwriting them.
5. If an existing target file differs from the source, summarize the difference and ask before replacing it.
6. Do not change unrelated files.

Codex import:
1. Determine `<CODEX_HOME>`.
   - Use the `CODEX_HOME` environment variable if present.
   - Otherwise use `~/.codex` as the default user-level path.
2. Create `<CODEX_HOME>/skills/ux-design-agent/`.
3. Copy:
   - `skillsets/ux-design-agent/codex/ux-design-agent/SKILL.md`
     to `<CODEX_HOME>/skills/ux-design-agent/SKILL.md`
   - `skillsets/ux-design-agent/codex/ux-design-agent/references/output-contract.md`
     to `<CODEX_HOME>/skills/ux-design-agent/references/output-contract.md`
   - `skillsets/ux-design-agent/codex/ux-design-agent/agents/openai.yaml`
     to `<CODEX_HOME>/skills/ux-design-agent/agents/openai.yaml`
4. If the active Codex runtime does not support UI metadata, still copy `openai.yaml` when the file can live beside the skill, but report that UI metadata support was not verified.

Claude Code import:
1. Determine the command target.
   - User-level default: `~/.claude/commands/ux-design-agent.md`
   - Project-level alternative: `<repo>/.claude/commands/ux-design-agent.md`
2. Copy `skillsets/ux-design-agent/claude/commands/ux-design-agent.md` to the selected command target.
3. Verify that the installed command invokes `/ux-design-agent` and says Claude Code orchestrates while Claude Design or equivalent design-execution tooling handles visual design work when available.
4. Do not claim Claude Design, Figma MCP, or any design-execution tool is connected unless you verified it in the active environment.

Verification:
1. List every installed or updated target file.
2. Compare each installed file against the source file, using byte-for-byte comparison when the environment supports it.
3. Report existing files that were left unchanged, replaced, or skipped.
4. Report missing source files, missing permissions, unavailable tool support, or skipped verification separately.
5. Confirm no unrelated files were changed.

After import, give me these try-it prompts:
- Codex: `Use $ux-design-agent to shape a Figma-first design system and layout workflow for my product.`
- Claude Code: `/ux-design-agent <product, Figma, repo, or design-system prompt>`

Safety rules:
- Do not include secrets or credentials in copied files, prompts, logs, or summaries.
- Do not mutate Figma files, repositories, cloud resources, trackers, or design-system libraries as part of import verification.
- Do not install or migrate component libraries during this import task.
- Do not push repository changes unless I explicitly ask you to push.
- If verification fails or access is blocked, stop and report the exact blocker plus the smallest safe next step.
```

## Compact Prompt

Use this when the assistant already has the config kit loaded:

```text
Import the UX Design Agent skillset from `https://github.com/albrand/ai-config-kit` or from the attached/readable local config-kit package if I provided one. Install the Codex skill from `skillsets/ux-design-agent/codex/ux-design-agent/` into `<CODEX_HOME or ~/.codex>/skills/ux-design-agent/`, including `SKILL.md`, `references/output-contract.md`, and `agents/openai.yaml`. Install the Claude Code command from `skillsets/ux-design-agent/claude/commands/ux-design-agent.md` into `~/.claude/commands/ux-design-agent.md` or the approved project `.claude/commands/` folder. Inspect existing targets before overwriting, ask before replacing customized files, verify installed files against the source, report skipped or blocked steps, and do not mutate Figma, repos, cloud resources, trackers, secrets, or component libraries during import.
```
