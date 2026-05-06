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
7. `docs/agent-framework/HARNESS_STRATEGY.md`
8. `docs/agent-framework/ARCHITECTURE_AND_CODE_QUALITY.md`
9. `docs/agent-framework/QUALITY_GATES.md`
10. `docs/agent-framework/QUALITY_CONVERGENCE.md`
11. `docs/agent-framework/REVIEW_AND_PR_FRAMEWORK.md`

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
- Harness capabilities: `[sub-agents/model routing/cache/validation executor availability]`
- Framework path and manifest: `[fill in]`
- Journaling requirement: `[enabled/disabled and path]`
- Release or deployment rules: `[fill in]`

## Required Behavior

- Analyze before acting.
- Plan before editing.
- Map the impacted surface.
- Verify the framework manifest and active harness capabilities.
- Route work through the harness only when useful and supported.
- Keep changes scoped.
- Run focused validation first.
- Report failed, blocked, skipped, and not-run checks explicitly.
