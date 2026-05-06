# AGENTS.md

Repo-specific instructions for AI coding agents working in this repository.

Replace bracketed placeholders before adoption. Do not publish closed-scope details in a shared template.

## Required First Steps

1. Read all applicable instruction files for the current directory.
2. Read the framework manifest and confirm required framework files are available.
3. Check whether the repository uses local session journals.
4. Read current task context and active source-of-truth docs.
5. Inspect current repository state before editing.
6. Present a concise plan before substantial edits.

## Source Of Truth Order

Use these sources in order:

1. Current user request.
2. Issue, ticket, or task acceptance criteria.
3. Approved designs, specs, architecture docs, or implementation docs.
4. Runtime contracts: schema, API payloads, auth rules, feature flags, logs, generated artifacts, and existing behavior.
5. Existing code conventions in the affected area.

If two sources conflict, stop and ask a direct question before implementing.

## Required Skills And Processes

- Use instruction discovery at the start of repo work and after changing directories.
- Use session journaling when enabled for this repository.
- Use harness routing when the tool supports sub-agents, model tiers, cache, or delegated validation.
- Use systematic debugging before patching bugs or unexpected behavior.
- Use big-change planning for architecture, auth, security, schema, migration, release, infrastructure, or broad refactor work.
- Use verification-before-completion before closing implementation, docs, config, workflow, or generated-artifact work.
- Use quality convergence when first-pass validation fails, quality targets are high, or the task is security, data, auth, release, or architecture sensitive.
- Use PR preparation guidance when creating, preparing, reviewing, or summarizing a branch or PR.

## Harness Capabilities

Fill in repo or tool-specific harness support:

- Framework path and manifest: `[path]`.
- Sub-agents available: `[yes/no/limited]`.
- Model routing available: `[yes/no/limited]`.
- Cache available: `[yes/no/limited]`.
- Validation executor available: `[yes/no/limited]`.
- File edit access available: `[yes/no/limited]`.
- Network or external tools available: `[yes/no/limited]`.
- Browser or UI verification available: `[yes/no/limited]`.

Defaults:

- The master agent owns judgment, architecture, escalation, integration, and final review.
- Delegated agents own only bounded execution slices with explicit validation.
- Use the smallest capable model or agent only when the result can be validated.
- Bypass cache when source-of-truth files changed or the user asks for fresh, current, repeated, or from-scratch analysis.
- Report unavailable, blocked, or unverified capabilities before relying on a fallback.
- Define breakpoints before high-risk phases, especially for architecture, security, data, release, destructive operations, and scope expansion.

## Pre-Edit Impact Mapping

Before substantial edits, map:

- Entry points.
- Callers and callees.
- Routes, handlers, jobs, commands, or scheduled tasks.
- Hooks, state stores, services, repositories, adapters, and shared helpers.
- Config, environment, generated artifacts, schemas, and migrations.
- Tests, fixtures, mocks, and snapshots.
- Relevant docs and release implications.
- Adjacent workflows that can regress.

Then state:

- Objective.
- Scope and non-goals.
- Assumptions.
- Recommended approach.
- Validation plan.
- Rollback or fallback path.

## Architecture Boundaries

Fill in repo-specific boundaries:

- Types live in `[path]`.
- Schemas live in `[path]`.
- Domain logic lives in `[path]`.
- Data access lives in `[path]`.
- UI components live in `[path]`.
- Hooks or state orchestration live in `[path]`.
- Tests live in `[path]`.
- Generated files are produced by `[command]` and should not be hand-edited unless explicitly allowed.

## Code Quality Doctrine

- Keep changes minimal and scoped.
- Prefer existing repo patterns over new abstractions.
- Keep modules small and single-purpose.
- Separate orchestration, data shaping, side effects, and presentation.
- Prefer explicit names, guard clauses, and simple control flow.
- Avoid hidden coupling, duplicated logic, and oversized files.
- Do not hardcode domain data, account IDs, schema assumptions, or secrets.
- Do not bypass lint, tests, auth checks, or release gates.

## Data And Security Rules

Fill in repo-specific rules:

- Account or workspace scoping key: `[key]`.
- Permission policy system: `[policy system]`.
- Environment access helper: `[helper]`.
- Public error response policy: `[policy]`.
- Webhook or external callback verification: `[policy]`.
- Secrets management: `[policy]`.

Required defaults:

- Preserve account/workspace isolation.
- Use least privilege.
- Validate external input.
- Do not return internal stack traces or sensitive third-party responses from public surfaces.
- Do not log secrets or sensitive values.

## State And Performance Rules

- Identify cache keys and invalidation paths before changing data flow.
- Avoid duplicate refetches and stale local copies.
- Prefer parallel loading when requests are independent.
- Use optimistic updates only with rollback and invalidation paths.
- Avoid nested repeated scans in hot paths; prefer indexed lookups or single-pass grouping.
- Keep rendering components free of avoidable data-shaping work.

## Testing Rules

- Bug fixes need regression tests that fail on the old behavior when feasible.
- Repeated validation failures require a convergence loop with target, max iterations, evidence, and stop reason.
- UI changes need behavior-level tests when practical.
- API changes need contract or handler tests.
- Shared helpers need edge-case unit tests.
- State-flow changes need tests for cache, invalidation, optimistic update, or rollback behavior.
- Security-sensitive changes need role, permission, or isolation coverage.

## Validation Commands

Replace placeholders with repo commands:

```bash
[focused test command for changed surface]
[lint command]
[typecheck command]
[test command]
[build command for PR-ready or cross-cutting work]
```

Report exact pass, fail, blocked, skipped, and not-run statuses.

## Optional Invokable Processes

Add explicit process names here. Only run them when the user invokes them.

Examples:

- `run the design-contract review`: compare changed UI against approved designs and changed contracts.
- `run the bugfix evidence process`: fix the bug, add behavior regression tests, update the issue, prepare the PR, and attach external evidence.
- `run the release readiness process`: validate build, checks, deployment notes, rollback, and operational risk.

## Completion Report

End code-changing tasks with:

- Changed surface.
- Source-of-truth references used.
- Harness capabilities used or unavailable, when relevant.
- Validation run, with exact pass/fail/blocked/skipped status.
- Self-review result.
- Residual risk.

Never claim completion when required checks failed, were blocked, or were not run.
