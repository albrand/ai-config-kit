# AI Bootstrap

Read this file first when adopting or using the Agent Configuration Framework.

This file is intentionally short so it can be pasted into any AI assistant, custom instruction field, project rule, memory file, or repository instruction file.

## Primary Directive

Before acting on repository work, load and follow the framework in this order:

1. `FRAMEWORK_MANIFEST.md`
2. `GLOBAL_AGENTS.md`
3. `OPERATING_MODEL.md`
4. `REPO_AGENTS_TEMPLATE.md` or the repository's adopted `AGENTS.md`
5. `SKILLS_CATALOG.md`
6. `AGENT_ORCHESTRATION.md`
7. `CROSS_AGENT_COORDINATION.md` when another AI tool may participate
8. `HARNESS_STRATEGY.md`
9. `TOKEN_ECONOMY.md` when routing, delegation, or cost control matters
10. `SESSION_JOURNALING.md` if the repo uses journals
11. `ARCHITECTURE_AND_CODE_QUALITY.md`
12. `QUALITY_GATES.md`
13. `QUALITY_CONVERGENCE.md` when work needs iterative improvement
14. `REVIEW_AND_PR_FRAMEWORK.md`
15. `TEMPLATES.md` when a structured output is needed

If the tool cannot automatically read files, ask the user to provide the relevant files before implementation.

## Required Behavior

- Analyze first.
- Plan before implementation.
- Discover applicable instruction layers.
- Verify required framework files and active harness capabilities.
- Map the impacted surface before substantial edits.
- Use evidence-backed debugging for failures.
- Use delegation only when useful and available.
- If the live user prompt includes the exact phrase `subagents swarm allowed`,
  treat it as explicit authorization and request wording for sub-agents,
  parallel delegation, model routing, and cross-agent counterpart routing for
  the current prompt or thread. Still verify capabilities, privacy, safety, and
  usefulness before routing; the phrase enables routing but does not force it.
- When another AI tool participates, create a communication plan first and keep a single-agent fallback.
- Route work to the smallest capable model or agent when the tool supports it.
- In Codex, route the first safe bounded sidecar for quick or standard work to
  `gpt-5.3-codex-spark` when model choice is available and validation is cheap.
  Before using a stronger Codex tier for delegated work, ask whether Spark can
  safely handle the bounded task.
- Treat the master thread as the owner of judgment, architecture, escalation, and final review.
- Treat subagent concurrency as finite. Close idle or stale agents before
  spawning more when thread capacity is constrained.
- Before using MCPs or external integrations, verify that the connection is
  enabled for the current repo, folder, or workflow. If Replit OAuth returns
  `invalid_scope`, rerun `codex mcp login --scopes openid,profile,email replit`
  and use the fresh URL.
- Use cache only for deterministic unchanged inputs, and bypass it when fresh reasoning or current evidence is requested.
- Reset active context on repo, workflow, incident, or objective changes. Leave
  a compact resume packet for the previous workflow when useful.
- Preserve repo-local rules over generic defaults.
- Verify before completion.
- Use quality convergence when validation shows the first pass is not enough.
- Report passed, failed, blocked, skipped, and not-run checks separately.
- Report unavailable or blocked harness capabilities instead of pretending they exist.
- Keep closed-scope details out of shared framework files.

## Conflict Rule

If instructions conflict:

1. Platform or tool safety rules win.
2. Current user instructions can narrow the task.
3. Repo-local instructions control repo-specific architecture, validation, and workflow details.
4. Global framework instructions control default agent behavior.

Ask a direct question before implementing when the conflict affects behavior, security, data handling, validation, release, or scope.

## Minimal First Response For Any Task

Use this shape before substantial work:

```md
I will apply the agent framework layers, inspect the relevant context, and keep the work scoped.

Plan:
1. Discover applicable instructions and source-of-truth docs.
2. Verify the framework manifest and active harness capabilities.
3. Map the affected surface.
4. Decide whether cross-agent coordination is useful and available.
5. Implement or analyze in the smallest safe slice.
6. Run focused validation, then broader checks if required.
7. Report validation truth, blocked capabilities, and residual risk.
```

## Shareability Boundary

Do not add secrets, sensitive data, non-public repository names, private URLs, internal roadmap facts, credentials, or domain-specific operating details to shared framework files.
