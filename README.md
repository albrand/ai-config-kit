# Plug-And-Play Agent Configuration Framework

This kit is a generic framework for configuring AI coding agents across teams and repositories.

It is intentionally free of closed-scope details. Do not add sensitive data, non-public repository names, private URLs, internal roadmap facts, credentials, or domain-specific operating details to the shareable version.

## What This Kit Provides

The kit defines how agents should:

- Verify the installed framework and active tool capabilities.
- Analyze before acting.
- Plan before editing.
- Discover and apply instruction layers.
- Use reusable skills.
- Use multi-agent orchestration when available and useful.
- Route work through a harness that keeps judgment, execution, cache, validation, and escalation separate.
- Keep session journals when a repository adopts journaling.
- Promote repeated workflows into durable skills or local rules.
- Apply architecture and code-quality requirements.
- Run quality gates and report exact validation truth.
- Iterate with quality convergence when a single pass does not meet the target.
- Review changes and prepare PRs from evidence.
- Adopt the framework in any repository without importing closed-scope context.

## File Map

- `AI_BOOTSTRAP.md`: first file any AI should read; short enough to paste into tools with no file discovery.
- `CONFIG_KIT_AI_PROMPT.md`: paste-ready prompt that tells any AI how to absorb the config kit.
- `FRAMEWORK_MANIFEST.md`: canonical file inventory, load profiles, harness capability record, and readiness matrix.
- `AI_TOOL_ADAPTERS.md`: setup guide for generic assistants and common AI coding tools.
- `GLOBAL_AGENTS.md`: user-level baseline instructions for all agent work.
- `REPO_AGENTS_TEMPLATE.md`: repo-root instruction template.
- `SKILLS_CATALOG.md`: recommended skills and skill design rules.
- `OPERATING_MODEL.md`: full layer model and execution lifecycle.
- `AGENT_ORCHESTRATION.md`: delegation, explorer/worker roles, ownership, and cleanup.
- `HARNESS_STRATEGY.md`: master/sub-agent routing, model tiers, cache rules, anti-drift, escalation, and validation.
- `SESSION_JOURNALING.md`: local session journal protocol.
- `CONTINUOUS_SKILL_LEARNING.md`: how repeated lessons become skills, rules, templates, or gates.
- `REPO_ADOPTION_PLAYBOOK.md`: step-by-step local adoption guide.
- `ARCHITECTURE_AND_CODE_QUALITY.md`: architecture review and code-quality doctrine.
- `QUALITY_GATES.md`: validation levels, commands, and truth-reporting rules.
- `QUALITY_CONVERGENCE.md`: iterative quality targets, scoring, breakpoints, and stop conditions.
- `REVIEW_AND_PR_FRAMEWORK.md`: review and PR preparation framework.
- `FRAMEWORK_PATTERNS.md`: neutral configuration patterns.
- `TEMPLATES.md`: copyable templates for common outputs.
- `INTERNAL_WIKI_PAGE.md`: short paste-ready wiki page.
- `adapters/`: copyable bootstrap files for tools that read project rules, memory files, or repo instruction files.

## Layer Model

Apply configuration from broad to narrow:

1. Platform and tool rules.
2. User-level global instructions.
3. Global skills.
4. Parent directory instructions.
5. Repo-root instructions.
6. Repo-local skills and process docs.
7. Current prompt.

Narrower layers add local context and constraints. If sources conflict, the agent should stop and ask a direct question before implementing.

`FRAMEWORK_MANIFEST.md` is the inventory and readiness contract. It does not replace policy files; it tells the AI which policy files to load, which harness capabilities are available, and what must be verified before adoption is considered complete.

## Adoption Summary

1. Give every AI tool `AI_BOOTSTRAP.md` and `FRAMEWORK_MANIFEST.md` as its first instructions.
2. For generic chat tools, paste `CONFIG_KIT_AI_PROMPT.md` before attaching or pasting the framework files.
3. Install the global baseline for the agent tool used by the team.
4. Install or define the global skills.
5. Add a repo-root instruction file from `REPO_AGENTS_TEMPLATE.md` or `adapters/AGENTS.md`.
6. Add a tool-specific adapter when useful, such as `adapters/CLAUDE.md`, `adapters/GEMINI.md`, or `adapters/cursor-agent-framework.mdc`.
7. Record which harness capabilities the active tool actually supports: model routing, sub-agents, cache, validation execution, file access, network access, and journals.
8. Decide whether the repo uses local session journals.
9. Define local source-of-truth docs, architecture boundaries, and validation commands.
10. Run a first-session verification prompt to confirm the agent sees the right layers and reports the capability map.
11. Improve the framework over time through the continuous skill learning process.

## Universal Bootstrap Contract

For any AI assistant, the first instruction is:

```text
Read CONFIG_KIT_AI_PROMPT.md if available. Then read AI_BOOTSTRAP.md and FRAMEWORK_MANIFEST.md first. Load the framework files relevant to the task. If you cannot access them, ask for them before substantial implementation.
```

The framework should work in three modes:

- File-aware mode: the AI reads the framework from the repository or shared folder.
- Paste mode: the user pastes `AI_BOOTSTRAP.md` plus the task-relevant files.
- Adapter mode: the repo includes a tool-specific adapter that imports or references the framework.

## Shareability Rules

- Keep the shared kit generic.
- Put closed-scope details only in each repo's private instruction files.
- Prefer placeholders over real names.
- Prefer workflow names over tool-specific names unless a tool is required.
- Keep examples neutral and broadly applicable.
