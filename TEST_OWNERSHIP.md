# Test Ownership

This doctrine makes the framework model-neutral about who owns test
evidence. It replaces blanket "every change needs a unit test" mandates with an
ownership- and boundary-based decision gate that selects the smallest falsifiable
evidence for the surface that actually owns the behavior.

`QUALITY_GATES.md`, `ARCHITECTURE_AND_CODE_QUALITY.md`,
`REVIEW_AND_PR_FRAMEWORK.md`, `REPO_AGENTS_TEMPLATE.md`, `README.md`,
`HARNESS_STRATEGY.md`, and the PR-review and ecosystem skillsets defer to this
file. Where an earlier doc restates a test rule, this file is canonical.

## Scope

This doctrine governs **new validation** required for a change. It is not a
deletion mandate. Existing tests are not automatically removed just because a
surface is reclassified here; leave them in place unless the team explicitly
decides to retire them. Use this gate when deciding what evidence a new change
must add or request.

## Ownership Classes

Classify the surface the change touches, then require evidence proportional to
that class.

### Repository-Owned Behavior And Invariants

Behavior, contracts, and invariants this repository owns and must keep working
require **durable regression protection** when the risk is high. Prefer the
smallest automated test, replay, contract check, or CI guard that fails if the
invariant breaks. "Durable" means it runs unattended on the changed surface and
catches a future regression, not a one-off proof.

### Integration Boundary

For code that calls or is called across a boundary this repository owns (API
handlers, SDK callers, message consumers, webhook receivers, data export/import),
own the **boundary contract**: request/response shape, auth, permissions, error
behavior, and isolation. Do not recreate the other side's internal suite; assert
the contract this repository depends on, at the boundary, with the smallest
falsifiable check.

### Third-Party Or Upstream Library

Do not recreate the upstream project's own test suite, exercise its internals, or
assert its private mechanics. The upstream project owns that coverage. Validate
only the **owned** assumption the repository relies on (version resolves, the
called API behaves as the repository expects) with the smallest check at the
call site or boundary. Upgrading a dependency is not a reason to add a parallel
upstream suite.

### Declarative Config Or Policy

For declarative config, policy, pipeline, workflow, IaC, or schema-as-config,
prefer the **native parser, linter, formatter, or planner** for that format
(`kubeconform`, `cfn-lint`, `tflint`/`terraform plan`, `actionlint`, schema
validators, YAML/JSON linters). Do not write existence tests for config mechanics
the native tool already checks. Add a test only when an **owned required runtime
asset or contract** must be present and the native tool cannot prove it (for
example, a required file the runtime loads, or a contract a consumer depends on).

### Migrations And Schema/Data Transformations

Do not unit-test a migration by asserting its raw SQL, text, or operation shape;
that couples tests to mechanics and to the migration tool's own behavior. When
the repository **owns** a schema or data transformation, require evidence
proportional to the risk:

- Isolated apply against a representative dataset or dry-run/plan output.
- Postconditions: the resulting schema/data/state matches the intended contract.
- Compatibility: existing callers, queries, jobs, and consumers still resolve.
- Rollback or forward-fix path: the change can be safely reversed or completed
  if it fails partway.

Prefer the migration tool's dry-run or plan, a schema-diff assertion on the
applied result, and a consumer/compatibility check over text-matching the
migration body.

### Generated Code

For generated, codegen, transpiled, or derived artifacts, do not hand-write a
parallel test suite for the generator's output mechanics. Require:

- Generator evidence: the generator ran and reported success, or a parity check
  that the output matches the source of generation.
- Consumer evidence: the generated artifact is consumable by its real consumer
  (compiles, imports, parses, typechecks, loads) at the smallest useful boundary.

Do not edit generated output by hand and then test the edit; fix the generator or
the source.

### Docs, Prompts, Policies, Framework Text

For documentation, prompts, policies, and framework text, use **Level 0** checks
from `QUALITY_GATES.md`: reference/link scan, manifest inventory check when
framework files change, closed-scope scan, markdown/format lint when available,
and encoding/ASCII check when required. Do not add unit tests for prose.

## Decision Gate: Smallest Falsifiable Evidence

For every change, run this gate and record the chosen evidence:

1. What behavior, contract, or invariant does this change touch?
2. Who **owns** that surface — this repository, an integration boundary, a
   third-party/upstream project, declarative config, a migration, a generator,
   or docs/policy?
3. What is the **smallest falsifiable evidence** that proves the owned behavior
   and would fail if it regressed? Prefer the cheapest layer that owns the truth.
4. Is the risk high enough (auth, data, security, money, release, durable
   invariant) that the evidence must be **durable** and run unattended?
5. Apply the ownership class above. If no class requires a new test, name the
   existing tool, contract check, or Level 0 check that already covers it.

The gate selects evidence; it never mandates a specific test layer universally.

## Manual QA

Manual QA, exploratory checks, screenshots, and one-off replays are **valid
evidence** for one-shot, visual, usability, or hard-to-automate outcomes. They
are **not durable regression protection** for high-risk owned invariants. When a
high-risk owned invariant is in scope, add durable automated protection or a CI
guard; do not substitute a manual check for it.

## Security

Security-sensitive behavior (auth, authorization, isolation, secrets, crypto,
external input, outbound requests) keeps **durable automated protection**: a test
or a CI guard that fails if the protection regresses. This is the one class where
durable automation is required, not merely proportional. See the Security Gate in
`QUALITY_GATES.md` and `SECURITY_AND_PENTEST.md`.

## Re-Review And Regression Scope

When re-reviewing a stable delta (a PR re-review, follow-up review, or queue
sweep), required new test evidence is scoped to what the **delta causally
affects**, not the whole current head. Do not expand blocking test requirements
to pre-existing or unrelated surfaces. See the delta-first re-review contract in
`REVIEW_AND_PR_FRAMEWORK.md` and `skillsets/pr-review/references/pr-review-output-contract.md`.

## Scenario Examples

- **Upstream library.** A change bumps a logging dependency. The upstream
  project owns its own suite. Do not recreate it. Add the smallest check that the
  repository's actual call site still behaves as expected, or rely on the existing
  consumer check if it already covers it.
- **Config parser.** A change edits a declarative CI workflow. Run `actionlint`
  and the native planner. Do not write an existence test for YAML mechanics the
  linter already validates. Add a test only if a required runtime asset the
  workflow depends on must be present.
- **Migration outcome.** A change adds a data migration. Do not assert the SQL
  text. Require an isolated apply or dry-run, postcondition checks on the
  resulting schema/data, a compatibility check for existing consumers, and a
  rollback/forward-fix path.
- **Generated artifact.** A change regenerates a client SDK. Require generator
  success or a parity check, plus consumer evidence the generated client compiles
  and imports. Do not hand-test generated internals.
- **Fixed blocker.** A re-review where the prior blocker was fixed. Drop the
  fixed finding; do not reopen it without changed facts. Require new evidence
  only for what the new delta causally affects.
- **Delta-caused adjacent regression.** A follow-up commit changes a helper that
  the prior delta's callers use. The helper change is in scope because there is a
  causal path; require evidence for that path only.
- **Unrelated legacy defect.** A re-review discovers a pre-existing bug in code
  the delta never touched. Report it as a non-blocking follow-up; do not block the
  delta on it.
- **Unavailable baseline.** The previously reviewed SHA is unreachable, so the
  old..new delta cannot be computed. Fall back to a full current-head review and
  state the fallback reason; test scope is the whole head only for that review.
- **Materially expanded scope.** A follow-up rewrites an auth boundary or data
  path. Scope materially expanded, so a full current-head review is justified and
  durable security/data protection may be required anew.
