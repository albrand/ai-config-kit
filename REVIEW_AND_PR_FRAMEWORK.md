# Review And PR Framework

Use this framework for code reviews, self-reviews, and PR preparation.

## Review Posture

Lead with findings. Prioritize:

1. Bugs and behavioral regressions.
2. Security, permission, and data-isolation risks.
3. Broken runtime contracts.
4. Missing tests for changed behavior.
5. Architecture or maintainability risks.
6. Performance regressions.
7. Documentation or release gaps.

If there are no findings, say that clearly and list residual risk or unverified checks.

## Review Scope

Before reviewing:

- Resolve the changed files.
- Identify the intended behavior.
- Identify source-of-truth docs.
- Identify runtime contracts.
- Identify relevant tests.
- Keep review scoped to the changed surface unless the user requests broader review.

## Review Criteria

Check:

- Request fidelity: change matches the ask.
- Source-of-truth fidelity: change matches accepted docs or designs.
- Runtime contract: inputs, outputs, auth, permissions, flags, env, cache, errors.
- Complexity: changed code remains understandable.
- Architecture: responsibilities stay in the right modules.
- State flow: no stale state, duplicate reloads, or cache drift.
- Data flow: no overfetching, missing filters, or broken pagination.
- Security: boundaries preserved.
- Tests: right layer and meaningful assertions.
- Validation: commands actually ran and results are truthful.

## Finding Format

Use:

```md
1. <path>:<line>
<What is wrong and why it matters.>
Question: <direct question if intent is unclear>
Recommendation: <specific fix or options>
```

Findings should include file references and be ordered by severity.

## Self-Review Before Completion

After editing, review your own diff:

- Re-read changed files.
- Compare against source of truth.
- Check architecture boundaries.
- Check state and data flow.
- Check security boundary.
- Check tests are behavior-focused.
- Check validation commands and outcomes.
- Fix safe issues before final response.
- Report issues that need broader scope or a decision.

## PR Preparation

Prepare PR bodies from real evidence, not memory.

Read:

- Actual diff.
- Changed files.
- Tests and validation output.
- Repo PR template.
- Release or deployment docs when relevant.

PR body should include:

- Problem.
- Approach.
- Important tradeoffs.
- Files or areas changed.
- Validation run.
- Deployment or operational impact.
- Rollback path.
- Residual risk.

Do not leave template sections blank. Use `N/A` if a section does not apply.

## Approval Standard

Approve or call ready only when:

- Changed behavior matches the request and source of truth.
- Runtime contracts are preserved.
- No blocking security or data risks remain.
- Focused validation supports the changed behavior.
- Required checks passed or gaps are explicitly non-blocking.
- Residual risk is documented.

Request changes or mark not ready when:

- The changed behavior is broken.
- Security or data boundaries are uncertain.
- Runtime contracts are broken.
- Required tests are missing for risky behavior.
- Validation is misleading or insufficient.
- The implementation hides scope expansion.

## Review Output Template

```md
Findings:
1. <finding>
2. <finding>

Open questions:
- <question or "None">

Validation reviewed:
- <command/output reviewed>

Residual risk:
- <risk or "None identified">
```

## PR Body Template

```md
## Problem

<What gap or defect this change addresses.>

## Approach

<What changed and why this approach.>

## Changed Surface

- <area/file>

## Validation

- <command>: <status>

## Deployment / Operations

<Impact, migration, env, monitoring, or N/A.>

## Rollback

<How to revert or contain.>

## Residual Risk

<Known gaps or "None identified".>
```
