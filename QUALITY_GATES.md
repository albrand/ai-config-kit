# Quality Gates

Quality gates prove that the requested outcome works and that important adjacent behavior did not regress.

## Validation Truth Rules

Always distinguish:

- Passed.
- Failed.
- Blocked.
- Skipped.
- Not run.

Never imply that skipped or unrun checks passed.

## Harness Validation Rules

When a harness routes work to delegated agents, smaller models, or another AI tool:

- Each code-producing delegated task should run, generate, or request validation tied to its contract.
- The master or coordinator must review delegated and counterpart validation before relying on it.
- Validation evidence should name the command, check, or direct behavior observed.
- A delegated or counterpart "looks good" is not validation evidence.
- Repeated validation failures should escalate to the master or strongest available model instead of broadening the patch.
- If counterpart access is blocked, unavailable, or unauthenticated, report that capability gap and run the strongest single-agent validation available.

## Evidence Requirement

Completion requires evidence.

For every non-trivial task, identify:

- Artifact produced.
- Requirement or source of truth it satisfies.
- Validation evidence.
- Remaining gap.

If there is no evidence, there is no completion. A confident assessment without an artifact and validation path should be reported as unverified.

## Gate Levels

### Level 0: Docs Or Prompt Only

Use for documentation, prompts, and framework text.

Suggested checks:

- Link/reference scan.
- Framework manifest inventory check when framework files changed.
- Closed-scope scan when content is shareable.
- Formatting or markdown lint if available.
- ASCII or encoding check if required by repo.
- Archive listing check when a distributable bundle is maintained.

### Level 1: Focused Change

Use for small code changes.

Required:

- Focused test or direct reproducer tied to the changed behavior.
- Lint or format check for changed files when available.
- Typecheck if the language supports it and the change touches typed code.

### Level 2: Standard Code Change

Use for normal implementation work.

Required:

- Focused tests.
- Lint.
- Typecheck.
- Relevant unit or integration tests.
- Diff whitespace check.

### Level 3: Cross-Cutting Change

Use for shared helpers, auth, data flow, state flow, build config, schema, or broad refactors.

Required:

- Level 2 checks.
- Full test suite or relevant broad suite.
- Build.
- Security or policy checks when applicable.
- Generated artifact checks when applicable.
- Regression tests for risky paths.

### Level 4: Release Or Deployment Change

Use for release, infrastructure, environment, migration, or deployment changes.

Required:

- Level 3 checks.
- Workflow syntax validation.
- Environment variable verification.
- Migration dry run or rollback plan when applicable.
- Deployment impact notes.
- Rollback procedure.
- Monitoring or verification plan.

## Bugfix Gate

For bugs:

1. Capture exact symptom.
2. Reproduce when feasible.
3. Identify root cause or state leading hypothesis.
4. Add regression protection when practical.
5. Re-run original reproducer.
6. Run one adjacent regression check when feasible.

Do not call a bug fixed only because code changed.

## UI Gate

For UI changes:

- Compare against approved design or local style guide.
- Test visible behavior, not only helper logic.
- Check loading, empty, error, and success states when relevant.
- Check keyboard and accessibility expectations when relevant.
- Check responsive behavior when relevant.

## API Gate

For API or handler changes:

- Validate request shape.
- Validate response shape.
- Validate auth and permission behavior.
- Validate error behavior.
- Avoid returning oversized or sensitive payloads.
- Add contract tests for important paths.

## Business Logic QA Gate

Use when tickets, docs, designs, roadmap items, or stakeholder requirements define expected behavior.

- Build a traceability matrix from requirement to source to expected behavior to QA evidence.
- Include positive paths, negative paths, permissions, state transitions, edge cases, data lifecycle, integrations, notifications, and reporting expectations when relevant.
- Treat docs, tickets, designs, and runtime behavior as separate sources. If they conflict, report the conflict before implementation or QA signoff.
- Do not invent missing requirements. Mark them as gaps, assumptions, or questions.
- Every generated implementation ticket should name the QA or test evidence that proves the business behavior.

## PR Review Gate

Use when reviewing a pull request, branch, or diff for merge readiness.

- Preflight the PR or diff before review: open, not draft unless explicitly requested, not trivial automated work, not already reviewed by the same AI reviewer unless asked.
- Resolve applicable instruction scope before making findings.
- Read PR title, body, linked issue, changed-file list, and author intent before reviewing details.
- Validate each candidate finding before reporting it.
- Drop speculative, lint-only, style-only, pre-existing, unscoped, or unsupported concerns.
- Report validation actually reviewed, including missing or misleading validation.
- Post public comments only when the user requested comment mode or repo policy requires it.
- Use committable suggestion blocks only when the suggestion fully fixes the issue.
- When addressing existing PR comments, inspect live comments, reviews, review threads, current head, checks, and deployment state before editing.
- Reply to each applicable comment after the fix or evidence lands, resolve only addressed threads, and request re-review if the new head invalidates approval.

## Data Gate

For data changes:

- Verify live or generated schema source of truth.
- Preserve account or workspace filters.
- Test null, empty, missing, duplicate, and invalid inputs.
- Verify migrations, generated clients, or schema artifacts when applicable.
- Check rollback or forward-fix path.

## Security Gate

For security-sensitive changes:

- Check authorization on server-side boundaries.
- Check account or workspace isolation.
- Check secret handling.
- Check logging and public error responses.
- Check webhook or callback verification.
- Include negative tests where practical.

## Validation Report Template

```md
Validation:

- <command>: passed
- <command>: failed - <short reason>
- <command>: blocked - <blocker>
- <command>: skipped - <why>
- <command>: not run - <why>

Direct behavior checked:

- <what proves the requested outcome>

Residual risk:

- <remaining gap or "None identified">
```

## Framework Adoption Gate

Use when installing or changing this framework:

1. Confirm `FRAMEWORK_MANIFEST.md` exists.
2. Confirm all canonical files listed in the manifest exist or are intentionally not adopted.
3. Confirm adapters point to the actual installed framework path.
4. Confirm repo-local instruction placeholders are filled in adopted repos.
5. Confirm the harness capability record is populated.
6. Confirm required validation commands are documented.
7. Confirm journaling is defined as required, optional, local-only, versioned, or disabled.
8. Run a closed-scope scan for shared files.
9. Run the first-session verification prompt.
10. Rebuild or refresh the distributable archive when one is used.

## Quality Convergence Gate

Use when quality needs iterative improvement:

1. Define quality dimensions and target score or pass criteria.
2. Define maximum iterations and plateau stop conditions.
3. Run the smallest useful implementation or review iteration.
4. Measure with direct evidence.
5. Feed failures and recommendations into the next iteration.
6. Stop when target quality is met, blocked, plateaued, or requires a user decision.
7. Report iteration count, evidence, current readiness, and remaining gaps.

## Handling Baseline Failures

If broad checks fail because of known or unrelated baseline issues:

- Say the command failed.
- Identify whether failures are in touched or untouched surfaces.
- Run focused checks for the changed surface when possible.
- Do not report the repo as green.
- Do not fix unrelated baseline issues unless the user expands scope.

## Minimum Completion Bar

Before completion:

- At least one direct validation should prove the requested outcome when feasible.
- Required repo gates should be run or explicitly reported as blocked/skipped.
- Residual risk should be visible.
