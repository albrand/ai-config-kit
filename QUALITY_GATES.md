# Quality Gates

Quality gates prove that the requested outcome works and that important adjacent behavior did not regress.

Test and validation requirements below are ownership- and boundary-gated by
`TEST_OWNERSHIP.md`: require new test evidence only when the changed surface owns
the behavior, contract, or invariant. Do not read these levels as a blanket
all-changes-need-tests mandate.

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

## Directive Challenge Gate

For non-trivial planning, architecture, framework, or skill changes, validation
must include a challenge pass. Verify that directives, journals, memories,
cached conclusions, and prior project patterns were treated as evidence, not
authority; that platform/tool safety, current explicit user instructions, repo
evidence, tests, runtime facts, and accepted criteria retained precedence; and
that any counterpart/advisor brief included the authorization sentence when
required.

When sibling projects were scanned for candidate patterns, report the scan
scope, why it was needed, and what evidence proved the selected pattern fit the
current repo.

## Evidence Requirement

Completion requires evidence.

For every non-trivial task, identify:

- Artifact produced.
- Requirement or source of truth it satisfies.
- Validation evidence.
- Remaining gap.

If there is no evidence, there is no completion. A confident assessment without an artifact and validation path should be reported as unverified.

## Gate Levels

Test evidence at every level is **ownership-gated**: require it only when the
changed surface owns the behavior, contract, or invariant being validated, per
`TEST_OWNERSHIP.md`. Do not treat the items below as a blanket mandate to add a
test to every change; select the smallest falsifiable evidence for the owning
surface. Upstream suites, declarative-config mechanics, migration text, and
generated internals are owned by their tools, not re-tested here.

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

Required when the changed surface owns the behavior:

- Focused test or direct reproducer tied to the changed behavior, or the smallest
  falsifiable evidence selected by `TEST_OWNERSHIP.md`.
- Lint or format check for changed files when available.
- Typecheck if the language supports it and the change touches typed code.

### Level 2: Standard Code Change

Use for normal implementation work.

Required when ownership and risk apply:

- Focused tests or boundary/contract checks for owned behavior.
- Lint.
- Typecheck.
- Relevant unit or integration tests when the repository owns that layer.
- Diff whitespace check.

### Level 3: Cross-Cutting Change

Use for shared helpers, auth, data flow, state flow, build config, schema, or broad refactors.

Required when ownership and risk apply:

- Level 2 checks.
- Full test suite or relevant broad suite when the repository owns the affected
  behavior and a broad run is the smallest falsifiable evidence.
- Build.
- Security or policy checks when applicable.
- Generated artifact checks via generator/parity/consumer evidence per
  `TEST_OWNERSHIP.md`.
- Regression protection for risky owned paths.

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
4. Add regression protection when practical and when the repository owns the
   failing behavior; select the smallest falsifiable evidence per
   `TEST_OWNERSHIP.md`.
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

- Preflight the PR or diff before review: open, not draft unless explicitly
  requested, not trivial automated work. Reuse a prior review only when the same
  authenticated reviewer reviewed the same head and no author reply followed;
  otherwise apply delta-first re-review.
- Resolve applicable instruction scope before making findings.
- Read PR title, body, linked issue, changed-file list, and author intent before reviewing details.
- Validate each candidate finding before reporting it.
- Drop speculative, lint-only, style-only, pre-existing, unscoped, or unsupported concerns.
- Report validation actually reviewed, including missing or misleading validation.
- For GitHub PRs, post a submitted review by default unless the user explicitly requested draft/no-post mode or posting is blocked.
- Prefer inline review threads on changed code over loose issue comments. Do not
  use one giant review body when changed lines can own the findings.
- Each substantive inline thread must include root cause, practical failure
  example, impact, and concrete code-level next step.
- Use committable suggestion blocks when the replacement is small, complete, and
  safe to apply as-is. Do not fabricate suggestion blocks for broad or uncertain
  fixes.
- Keep public PR surfaces transcript-free: no `Validation reviewed` blocks,
  command-by-command pass lists, `git diff --check passed`,
  `git merge-tree succeeded`, `no checks reported`, or board-access caveats in
  PR comments or PR bodies.
- Keep PR bodies minimal: `Summary`, `Changes and value`, and `Ticket` only when
  a ticket applies. Do not add approach, validation, deployment, risk,
  follow-up, checklist, rollback, residual-risk, testing, or command-log
  sections.
- Do not add AI attribution or generated-by signatures to PR surfaces.
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

For security-sensitive changes. This gate is the checklist; `SECURITY_AND_PENTEST.md`
is the full doctrine, and the security-review skillset is the executable form.

Coverage (examine the categories that apply; do not report a category clean
unless it was actually examined):

- Broken access control: server-side authorization on every boundary, account /
  workspace / tenant isolation, no client-trusted authz, no IDOR.
- Injection: SQL/NoSQL, command, template, header, and path injection;
  parameterization and context-correct escaping.
- Authentication & session: credential handling, session fixation, token
  lifetime and rotation.
- Cryptographic & secret handling: no secrets in code/logs/config, no weak or
  homemade crypto, encryption in transit and at rest where required.
- SSRF and unsafe outbound requests: user-controlled URLs, metadata-endpoint
  reachability, allow-listing.
- Supply-chain & malicious dependencies (weight first — the demonstrated
  real-world failure mode): review dependency/lockfile changes against the code
  change; scan build/config files for appended code, obfuscation markers,
  `child_process`/`eval` in config, dynamic `require` added to ESM, and
  zero-width Unicode; check lifecycle scripts. Use
  `skillsets/security-review/references/supply-chain-iocs.md`.
- Security misconfiguration: default creds, verbose errors, permissive CORS,
  missing security headers, exposed admin surfaces.
- Logging & monitoring: no secrets in logs, no sensitive data in public error
  responses, adequate security audit trail.

Validation requirements:

- Rate severity on **residual** exposure after existing mitigations, not on the
  raw scanner label (residualize — see the causal protocol in
  `DIRECTIVE_CHALLENGE_AND_CAUSAL_INFERENCE.md`).
- For high-stakes or broad security review, use **multi-pass reinforcement**:
  several independent, blind finder passes with different lenses, then an
  adversarial refute pass that only confirms findings surviving cross-checking,
  looping until dry. A single pass is not sufficient for a security sign-off.
- Include negative tests where practical, and add a regression test or CI guard
  for each confirmed finding.
- For active testing against a running target, the authorization gate in
  `SECURITY_AND_PENTEST.md` must pass first; otherwise stay static.
- Keep exploit-validation, severity, and fix-design judgment on the strongest
  reasoning path (see the security routing tier in `HARNESS_STRATEGY.md`).

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
