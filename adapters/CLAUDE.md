# CLAUDE.md

This repository uses the Agent Configuration Framework.

Read the framework before substantial repository work:

@docs/agent-framework/AI_BOOTSTRAP.md
@docs/agent-framework/FRAMEWORK_MANIFEST.md
@docs/agent-framework/GLOBAL_AGENTS.md
@docs/agent-framework/OPERATING_MODEL.md
@docs/agent-framework/AGENT_ORCHESTRATION.md
@docs/agent-framework/CROSS_AGENT_COORDINATION.md
@docs/agent-framework/HARNESS_STRATEGY.md
@docs/agent-framework/TOKEN_ECONOMY.md
@docs/agent-framework/ARCHITECTURE_AND_CODE_QUALITY.md
@docs/agent-framework/QUALITY_GATES.md
@docs/agent-framework/QUALITY_CONVERGENCE.md
@docs/agent-framework/REVIEW_AND_PR_FRAMEWORK.md
@docs/agent-framework/skillsets/pr-review/README.md
@docs/agent-framework/skillsets/pr-review/references/pr-review-output-contract.md

## Repo-Specific Overlay

Replace this section with local rules:

- Source-of-truth order: `[fill in]`
- Architecture boundaries: `[fill in]`
- Required validation commands: `[fill in]`
- Harness capabilities: `[sub-agents/cross-agent counterpart/model routing/cache/validation executor availability]`
- MCP and external integration routing: `[repo/folder/workflow allow-list or disabled]`
- Framework path and manifest: `[fill in]`
- Journaling requirement: `[enabled/disabled and path]`
- Release or deployment rules: `[fill in]`

## Required Behavior

- Analyze before acting.
- Plan before editing.
- Map the impacted surface.
- Verify the framework manifest and active harness capabilities.
- Route work through the harness only when useful and supported.
- If the live user prompt includes the exact phrase `subagents swarm allowed`,
  treat it as explicit authorization and request wording for sub-agents,
  parallel delegation, model routing, and cross-agent counterpart routing when
  useful and supported, without bypassing capability, privacy, safety, budget,
  stop-condition, anti-drift, or validation checks.
- When another AI tool participates, create the communication plan before joint
  work and keep a single-agent fallback.
- Route bounded delegated work to the smallest capable Claude Code agent
  (`Explore` or `Agent(model: "haiku")` for read-only or classification work,
  `Agent(model: "sonnet")` or `general-purpose` for localized code and tests).
  Keep architecture, security, data-loss, ambiguity, and final review on the
  master thread plus `advisor`.
- Treat subagent concurrency as a finite runtime budget. Do not spawn
  speculative agents.
- Close completed, idle, stale, or prior-workflow agents after capturing any
  needed result or resume packet, and open fresh agents for new delegated work
  instead of reusing stale context.
- Before using MCPs or external integrations, confirm they are enabled for the
  current repo, folder, or workflow. Ask before using unrecorded connections.
- Reset active context on workflow, repo, incident, or objective changes.
- Keep changes scoped.
- Run focused validation first.
- Report passed, failed, blocked, skipped, and not-run checks explicitly. Never
  imply skipped or unrun checks passed.
- Verify before completion. Completion requires artifact plus validation
  evidence; otherwise report the outcome as unverified.

## Optional Claude Code Commands

If this repo installs framework commands, copy command files from
`docs/agent-framework/skillsets/*/claude/commands/` into `.claude/commands/`
or `~/.claude/commands/`.

For operator-facing examples, read
`docs/agent-framework/ECOSYSTEM_TERRAFORM_GUIDE.md`.

Common framework commands:

- `/plan-module-delivery`
- `/roadmap-terraform`
- `/tech-terraform`
- `/assess-then-harden`
- `/code-review`
