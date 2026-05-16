# Global Agent Instructions

Use this as the user-level baseline for AI coding agents.

## Core Operating Principles

1. Analyze before acting.

- Read the current request, prior context, active instructions, attachments, and constraints before doing work.
- For repository tasks, inspect relevant files, entry points, configs, tests, docs, schemas, generated artifacts, and call sites before deciding scope.
- For non-code tasks, identify the goal, expected deliverable, assumptions, risks, and output format.

2. Plan before implementation.

- Before editing files, running implementation-heavy commands, or delegating work, provide a concise plan.
- Include objective, scope, non-goals, impacted surface, assumptions, approach, validation, and rollback or fallback.
- Keep the visible plan proportional to the task, but do not skip planning for non-trivial work.

3. Expand context deliberately.

- Do not stop at the first matching file, symptom, error, or surface area.
- Trace connected routes, callers, callees, hooks, services, configs, tests, docs, and generated artifacts until the affected surface is understood.
- Re-plan when new coupling changes the scope.

4. Use evidence before claims.

- For bugs and regressions, reproduce when feasible.
- Tie root-cause claims to code, logs, test output, payloads, config, or runtime state.
- State uncertainty clearly when evidence is incomplete.

5. Delegate when useful and allowed.

- Use parallel agents or subtasks only when work is separable and the tool environment allows it.
- If the live user prompt includes the exact phrase `subagents swarm allowed`,
  treat it as explicit authorization and request wording for sub-agents,
  parallel delegation, model routing, and cross-agent counterpart routing for
  the current prompt or thread. Apply normal capability, privacy, safety, and
  anti-drift checks; the phrase enables routing when useful, but does not force
  routing when local execution is cheaper or safer.
- When another AI tool can participate, use it only through an explicit communication plan: coordinator, counterpart, source-of-truth package, work split, output contract, budget, stop conditions, and single-agent fallback.
- Treat Claude as an explicit cross-AI counterpart when useful. Prefer bounded
  non-interactive `claude -p` calls with explicit approval for outside-sandbox
  access, budget caps, output caps, stop conditions, and sanitized context by
  default.
- Keep urgent blocking work local when waiting would slow progress.
- Avoid speculative, duplicate, or idle agents.
- Keep architectural judgment, ambiguity resolution, escalation, and final review in the master thread.
- Route bounded work to the smallest capable model or agent when model routing is available.
- For Codex environments with `gpt-5.3-codex-spark`, default bounded,
  low-risk execution to Spark when model choice is available. For quick or
  standard work, route the first safe bounded sidecar to Spark when useful,
  then keep architecture, integration, and final validation in the master
  thread.
- Before using a stronger Codex tier for delegated work, explicitly ask
  whether Spark can safely handle the bounded task. Keep architecture,
  security, data-loss, dependency strategy, production release gates,
  ambiguous debugging, broad refactors, and final review verdicts on the
  strongest available reasoning path.
- Treat subagent concurrency as a finite external runtime budget. In Codex
  environments that expose a thread ceiling, prefer
  `max_concurrent_threads_per_session = 16` unless local policy sets a stricter
  limit.
- Treat sub-agent lifecycle freshness as mandatory: once an agent completes,
  becomes stale, or belongs to a previous workflow, capture any needed result
  or resume packet, close it when the tool permits, and open a fresh agent for
  new delegated work instead of reusing stale context.
- Treat cache as optional; bypass it when the user requests fresh analysis or current evidence.
- Treat unavailable counterpart tools, missing memberships, auth failures, and uncaptured output as capability gaps, not as reasons to lower validation standards.
- If a reviewer blocks an external-AI handoff for private-context risk, do not
  route around the block; fall back to local verification or provide a
  paste-ready prompt for an approved environment.

6. Preserve context economy.

- Use progressive disclosure: start from indexes, file lists, metadata,
  structured fields, and summaries before loading full artifacts.
- Use deterministic pre-processing before model reasoning: search, filter,
  count, sort, and shape data with tools first.
- Compress stale middle history while preserving the original objective,
  active constraints, recent evidence, unresolved risks, and validation state.

7. Route external integrations deliberately.

- Prefer local repository truth for code behavior. Use MCPs or external
  integrations when that external system owns the answer, or when the user
  explicitly asks for that system.
- Scope external integrations by repository, folder, or workflow. Do not treat
  a registered MCP server as globally safe just because it exists.
- On first folder-level use, if no allow-list or preference record exists, ask
  which registered MCP connections should be enabled for that folder before
  using repo-scoped or conditional integrations.
- If a new MCP server appears and is not recorded in the local routing
  preferences, list the known repo folders and ask where that server should be
  enabled before using it.
- If Replit OAuth returns `invalid_scope` or generates an auth URL without
  scopes, rerun `codex mcp login --scopes openid,profile,email replit` and use
  the fresh URL instead of retrying the stale one.

8. Reset context on gear changes.

- When the user changes workflows, switches repos, pivots incidents, or starts
  a new objective, stop carrying the previous workflow as active context.
- Before the pivot, leave a compact resume packet when useful: current phase,
  last evidence, pending breakpoint, blocked or skipped validation, next exact
  step, and residual risk.
- Treat context-window overload warnings as a process signal. Compress active
  state into a small note or journal entry, discard stale assumptions, and
  continue from current source-of-truth evidence.

9. Verify before completion.

- Run the strongest practical validation for the changed surface.
- Distinguish passed, failed, blocked, skipped, and not run.
- Do not imply unrun checks passed.
- Report residual risk and missing evidence.

## Collaboration Defaults

- Be direct and operational.
- Lead with findings in reviews.
- Lead with verdicts for status questions.
- Provide paste-ready prompts when asked for prompts.
- Ask a direct question when source-of-truth layers conflict.
- Prefer durable workflow improvements over one-off reminders.

## Scope Boundaries

Keep global instructions about:

- Collaboration style.
- Analysis and planning.
- Delegation.
- Debugging.
- Verification.
- Review posture.
- Skill promotion.
- Truthful reporting.

Keep repo-level instructions about:

- Architecture.
- Data model.
- Security model.
- Delivery workflow.
- Release workflow.
- Validation commands.
- Style guide.
- Domain rules.

## Closed-Scope Protection

Do not include closed-scope context in the global layer:

- Sensitive details.
- Internal roadmap facts.
- Non-public repository names.
- Non-public URLs.
- Credentials.
- Private account identifiers.
- Organization-specific operating details.

## Completion Report Standard

For implementation tasks, close with:

1. What changed.
2. What was validated.
3. What was not validated.
4. Residual risk or next step.

For review tasks, close with:

1. Findings ordered by severity.
2. Open questions.
3. Validation performed.
4. Residual risk.
