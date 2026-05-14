# GEMINI.md

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
- When another AI tool participates, create the communication plan before joint work and keep a single-agent fallback.
- Before using MCPs or external integrations, confirm they are enabled for the
  current repo, folder, or workflow. Ask before using unrecorded connections.
- Reset active context on workflow, repo, incident, or objective changes.
- Keep changes scoped.
- Verify before completion.
