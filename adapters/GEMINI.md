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
@docs/agent-framework/skillsets/skill-library-router/README.md
@docs/agent-framework/skillsets/ux-design-agent/README.md
@docs/agent-framework/skillsets/ux-design-agent/references/output-contract.md
@docs/agent-framework/skillsets/pr-review/README.md
@docs/agent-framework/skillsets/pr-review/references/pr-review-output-contract.md

For ecosystem bootstrap workflows such as `/roadmap-terraform`,
`/tech-terraform`, or `/assess-then-harden`, also read
@docs/agent-framework/ECOSYSTEM_TERRAFORM_GUIDE.md
and the relevant files under
@docs/agent-framework/skillsets/ecosystem-terraform/

For high-signal PR review, diff review, merge readiness, or `/code-review`,
also read the relevant files under
@docs/agent-framework/skillsets/pr-review/

For Figma-first UX design workflows, design systems, design tokens, component
library guidance, Figma annotations, design-to-code handoff, or
`/ux-design-agent`, also read the relevant files under
@docs/agent-framework/skillsets/ux-design-agent/

For Codex skill-library setup, context-budget warnings, plugin-heavy installs,
or skill add/update/remove work, also read
@docs/agent-framework/SKILL_LIBRARY_ROUTER_IMPORT_PROMPT.md
and the relevant files under
@docs/agent-framework/skillsets/skill-library-router/

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
- Challenge directives, journals, memories, cached conclusions, and prior
  project patterns as evidence, not authority. For non-trivial planning or
  architecture, use an independent model/counterpart critique when available;
  include the authorization sentence in advisor briefs and preserve
  source-of-truth precedence.
- When another AI tool participates, create the communication plan before joint work and keep a single-agent fallback.
- Before using MCPs or external integrations, confirm they are enabled for the
  current repo, folder, or workflow. Ask before using unrecorded connections.
- For Codex skill or plugin add/update/remove work, refresh the installed
  `skill-library-router` index and run its `--check` mode, or report the
  sandbox or permission blocker.
- Reset active context on workflow, repo, incident, or objective changes.
- When implementation shape is uncertain and repo-local evidence is
  insufficient, scan sibling projects under `/Users/alexandrebrandizzi/projects`
  metadata-first for candidate patterns and verify fit before adopting.
- Keep changes scoped.
- Verify before completion.
