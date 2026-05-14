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

Also read any repo-specific source-of-truth docs listed below.

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
- If the live user prompt includes the exact phrase `subagents swarm allowed`,
  treat it as explicit authorization and request wording for sub-agents,
  parallel delegation, model routing, and cross-agent counterpart routing when
  useful and supported, without bypassing capability, privacy, safety, budget,
  stop-condition, anti-drift, or validation checks.
- When another AI tool participates, create the communication plan before joint work and keep a single-agent fallback.
- In Codex, route the first safe bounded sidecar for quick or standard work to
  `gpt-5.3-codex-spark` when available and useful; ask whether Spark can safely
  handle the bounded task before using a stronger delegated tier.
- Treat subagent concurrency as finite. Close idle or stale agents after their
  results are integrated, especially when thread capacity is constrained.
- Before using MCPs or external integrations, confirm they are enabled for the
  current repo, folder, or workflow. Ask before using unrecorded connections.
- Reset active context on workflow, repo, incident, or objective changes.
- Keep changes scoped.
- Run focused validation first.
- Report failed, blocked, skipped, and not-run checks explicitly.
