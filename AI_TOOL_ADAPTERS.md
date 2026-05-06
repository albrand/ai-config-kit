# AI Tool Adapters

This file explains how to make the framework readable by different AI tools.

The core idea is simple: every tool needs a small bootstrap instruction that points it to the same framework files. Tool-specific files should contain only routing instructions and local repo details, not a forked copy of the entire framework.

## Universal Setup

Use this for any AI assistant:

1. Give the AI `CONFIG_KIT_AI_PROMPT.md` when available.
2. Give the AI `AI_BOOTSTRAP.md`.
3. Give the AI `FRAMEWORK_MANIFEST.md`.
4. Give the AI `README.md`.
5. Give the AI the relevant framework file for the task:
   - Planning: `OPERATING_MODEL.md`
   - Debugging: `OPERATING_MODEL.md` plus `QUALITY_GATES.md`
   - Code quality: `ARCHITECTURE_AND_CODE_QUALITY.md`
   - Harness, model routing, cache, or delegation: `AGENT_ORCHESTRATION.md` plus `HARNESS_STRATEGY.md`
   - Quality convergence: `QUALITY_CONVERGENCE.md` plus `QUALITY_GATES.md`
   - Review or PR: `REVIEW_AND_PR_FRAMEWORK.md`
   - Journaling: `SESSION_JOURNALING.md`
   - Skill creation: `CONTINUOUS_SKILL_LEARNING.md` plus `SKILLS_CATALOG.md`
6. For repo work, also give the AI the repo's local instruction file.
7. Ask the AI to report the active harness capability record before substantial work.

If the tool supports repository instruction files, place a copy of `adapters/AGENTS.md` or an equivalent bootstrap file at the repo root and edit the local paths.

## Generic Chat Assistant

Use when the tool has no special project memory or repo rules.

Copy `CONFIG_KIT_AI_PROMPT.md` into the chat, then attach or paste the framework files needed for the task.

Use `adapters/GENERIC_AI_PROMPT.md` only when you need a short fallback prompt.

Best for:

- One-off planning.
- External reviews.
- Vendor-neutral setup.
- Tools with no file discovery.

## AGENTS-Compatible Tools

Use `adapters/AGENTS.md` as the repo-root bootstrap file.

Best for tools that read `AGENTS.md` or similar markdown agent instructions.

Repo-root pattern:

```text
AGENTS.md
docs/agent-framework/
  AI_BOOTSTRAP.md
  FRAMEWORK_MANIFEST.md
  GLOBAL_AGENTS.md
  OPERATING_MODEL.md
  ...
```

If the tool supports nested instruction files, use additional nested `AGENTS.md` files only for local overrides.

## Cursor

Cursor supports project rules in `.cursor/rules` and user rules in settings. Current Cursor docs also describe `AGENTS.md` as a markdown alternative to project rules.

Recommended setup:

- Put global personal preferences in Cursor User Rules.
- Put repository rules in `AGENTS.md` or `.cursor/rules`.
- For project rules, copy `adapters/cursor-agent-framework.mdc` into `.cursor/rules/agent-framework.mdc`.
- Keep the rule concise and point it at the framework files instead of duplicating every detail.

## Gemini CLI

Gemini CLI uses `GEMINI.md` context files and hierarchical memory. It also supports imports with `@file.md` syntax and configurable context filenames.

Recommended setup:

- Copy `adapters/GEMINI.md` to the repo root.
- Keep the framework files in a stable folder, for example `docs/agent-framework/`.
- Use imports from `GEMINI.md` to load the bootstrap and repo instructions.
- If your team standardizes on `AGENTS.md`, configure Gemini CLI context filenames to include it.

## Claude Code

Claude Code uses `CLAUDE.md` memory files at several levels, including user-level and project-level memory. It supports imports with `@path` syntax.

Recommended setup:

- Put personal global preferences in the user-level memory file.
- Copy `adapters/CLAUDE.md` to the repo root for project memory.
- Use imports from `CLAUDE.md` to point to the framework files.
- Keep local-only preferences out of shared project memory.

## Codex

Codex can be guided by `AGENTS.md` files placed in the repository. `AGENTS.md` files can describe how to navigate the codebase, run tests, and follow project practices.

Recommended setup:

- Copy `adapters/AGENTS.md` to the repo root.
- Place framework files under a stable path such as `docs/agent-framework/`.
- Put repo-specific validation commands and architecture rules in the repo `AGENTS.md`.
- Use nested `AGENTS.md` files only for subtrees with different rules.

## Any Other AI Tool

Use the fallback pattern:

1. Paste `AI_BOOTSTRAP.md`.
2. Paste `CONFIG_KIT_AI_PROMPT.md` if available.
3. Paste `FRAMEWORK_MANIFEST.md`.
4. Paste `GLOBAL_AGENTS.md`.
5. Paste `OPERATING_MODEL.md`.
6. Paste the repo-specific instructions.
7. Paste only the specialized framework file needed for the task.

Ask the AI to confirm:

```text
List the instruction layers you will follow.
State which file controls global behavior.
State which file controls repo-specific behavior.
State which harness capabilities you can use: sub-agents, model routing, cache, and validation execution.
State any missing required framework files.
State which validation gates apply.
Do not edit files yet.
```

## Adapter Maintenance

- Keep adapters short.
- Keep detailed policy in the framework files.
- Do not fork framework policy into every tool-specific file.
- Update adapters when a tool changes its instruction file conventions.
- Prefer public, documented entry points over unofficial behavior.

## Reference Links

These public docs were checked when this adapter guide was written:

- Cursor Rules: https://docs.cursor.com/context/rules
- Gemini CLI `GEMINI.md`: https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/gemini-md.md
- Claude Code memory: https://docs.anthropic.com/en/docs/claude-code/memory
- Codex and `AGENTS.md`: https://openai.com/index/introducing-codex/
