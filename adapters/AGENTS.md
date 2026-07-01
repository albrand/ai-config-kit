# AGENTS.md

This repository uses the Agent Configuration Framework.

## Bootstrap

Before substantial repository work, read:

1. `docs/agent-framework/AI_BOOTSTRAP.md`
2. `docs/agent-framework/FRAMEWORK_MANIFEST.md`
3. `docs/agent-framework/GLOBAL_AGENTS.md`
4. `docs/agent-framework/OPERATING_MODEL.md`
5. `docs/agent-framework/REPO_AGENTS_TEMPLATE.md`
6. `docs/agent-framework/AGENT_ORCHESTRATION.md`
7. `docs/agent-framework/CROSS_AGENT_COORDINATION.md`
8. `docs/agent-framework/HARNESS_STRATEGY.md`
9. `docs/agent-framework/TOKEN_ECONOMY.md`
10. `docs/agent-framework/ARCHITECTURE_AND_CODE_QUALITY.md`
11. `docs/agent-framework/QUALITY_GATES.md`
12. `docs/agent-framework/QUALITY_CONVERGENCE.md`
13. `docs/agent-framework/REVIEW_AND_PR_FRAMEWORK.md`
14. `docs/agent-framework/skillsets/skill-library-router/README.md`
15. `docs/agent-framework/skillsets/ux-design-agent/README.md`
16. `docs/agent-framework/skillsets/ux-design-agent/references/output-contract.md`
17. `docs/agent-framework/skillsets/pr-review/README.md`
18. `docs/agent-framework/skillsets/pr-review/references/pr-review-output-contract.md`

Also read any repo-specific source-of-truth docs listed below.

For ecosystem bootstrap workflows such as `/roadmap-terraform`,
`/tech-terraform`, or `/assess-then-harden`, also read
`docs/agent-framework/ECOSYSTEM_TERRAFORM_GUIDE.md` plus the relevant
`docs/agent-framework/skillsets/ecosystem-terraform/` files.

For high-signal PR review, diff review, merge readiness, or `/code-review`,
also read `docs/agent-framework/skillsets/pr-review/` files.

For Figma-first UX design workflows, design systems, design tokens, component
library guidance, Figma annotations, design-to-code handoff, or
`/ux-design-agent`, also read
`docs/agent-framework/skillsets/ux-design-agent/` files.

For Codex skill-library setup, context-budget warnings, plugin-heavy installs,
or skill add/update/remove work, also read
`docs/agent-framework/SKILL_LIBRARY_ROUTER_IMPORT_PROMPT.md` and
`docs/agent-framework/skillsets/skill-library-router/` files.

## Repo-Specific Overlay

Replace this section with local rules:

- Source-of-truth order:
  1. Current user request.
  2. Issue or task acceptance criteria.
  3. Approved designs, specs, or architecture docs.
  4. Runtime contracts and existing behavior.
  5. Existing code conventions in the affected area.
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
- If the live user prompt includes the exact phrase `subagents swarm allowed`,
  treat it as explicit authorization and request wording for sub-agents,
  parallel delegation, model routing, and cross-agent counterpart routing when
  useful and supported, without bypassing capability, privacy, safety, budget,
  stop-condition, anti-drift, or validation checks.
- When another AI tool participates, create the communication plan before joint work and keep a single-agent fallback.
- Use a configured local sidecar first for compact no-tool cognition; cap
  output, use tool-free system instructions, and verify before acting.
- When local-sidecar delegation is required, make multiple independent
  no-tool delegations and reconcile their outputs before implementation or
  final judgment.
- In Codex, route the first safe bounded tool/file sidecar for quick or
  standard work to GPT 5.3 Spark when available and useful. When a Codex model
  slug is required, use `gpt-5.3-codex-spark`; record the exception reason
  before using a stronger delegated tier.
- Treat subagent concurrency as finite. In Codex environments that expose a
  thread ceiling, prefer `max_concurrent_threads_per_session = 16` unless local
  policy sets a stricter limit.
- Close completed, idle, stale, or prior-workflow agents after capturing any
  needed result or resume packet, and open fresh agents for new delegated work
  instead of reusing stale context.
- Before using MCPs or external integrations, confirm they are enabled for the
  current repo, folder, or workflow. Ask before using unrecorded connections.
- Use the skill-library router proactively. Before assuming no specialized skill
  applies, match task language against the refreshed index's names, aliases,
  routing terms, search text, plugin/source, and paths; load the narrowest
  matching skill directly even when the user did not name it.
- For Codex skill or plugin add/update/remove work, refresh the installed
  `skill-library-router` index and run its `--check` mode, or report the
  sandbox or permission blocker.
- Reset active context on workflow, repo, incident, or objective changes.
- When implementation shape is uncertain and repo-local evidence is
  insufficient, scan sibling projects under `/Users/alexandrebrandizzi/projects`
  metadata-first for candidate patterns and verify fit before adopting.
- Keep changes scoped.
- Run focused validation first.
- Report failed, blocked, skipped, and not-run checks explicitly.
