---
name: meaningful-tests
description: Use before selecting or reporting tests, claiming a feature or workflow complete, or exercising a product as its user. Require a named persona, identified target, stated user outcomes, and a verdict per outcome; preserve evidence boundaries and fix authorized workflow failures.
verify: python3 scripts/verify-contract.py
verified: 2026-10-01
---

# Meaningful tests

## Name the outcome and its evidence

A workflow test names a persona, known starting state, target URL or stack with
commit SHA or deployment identity, and user-outcome goal. Exercise the real
interface the persona uses, then record one verdict for that goal:

- PASS: the persona completed the goal, including required unchanged steps.
- FAIL: an attempted goal did not complete. A broken state is a failure, not an
  observation or a scope excuse.
- BLOCKED: the goal could not be attempted; name the specific missing input,
  permission, capability, or external state.
- NOT RUN: no attempt or adequate evidence exists. Never imply it passed.

Report a verdict per goal. A PASS for one goal remains valid when another goal
fails, but the full workflow cannot be called complete. State failed or blocked
required goals clearly; do not make the headline greener than its contents.
Formatting, label order, or a table does not change whether evidence exists.

## Keep evidence at the owning boundary

Unit and component checks establish their exercised contracts; they do not prove
the entire application works. A successful API response does not prove the
user can reach or understand the action. Lint, typecheck, and build results
establish their specific checks. Rendered labels or an element's presence do
not establish layout, chart geometry, or a completed user goal.

Choose focused checks that can detect the defect. For a regression, demonstrate
the new check fails against the old behavior when feasible. Count the tests
that actually ran and investigate empty or skipped suites. Do not invent tests
for declarations or generated internals when a check at their consumer owns
the behavior. Use `TEST_OWNERSHIP.md` when the repository adopts that contract.

## Exercise the complete requested workflow

Walk from the persona's entry point through its final outcome, including setup,
authorization, unchanged steps, and applicable unhappy paths: wrong role,
missing prerequisite, invalid input, denied permission, cancellation, back,
close, undo, retry, and logout. Test only applicable states; do not introduce
unrelated personas or infrastructure merely to fill a checklist.

When a committed `.qa/config.json` exists, use the repository's `qa-sweep`
inventory and ship gate. Inventory a walk's defects before batching related
fixes, run focused checks, and re-walk the complete journey at the final batch
head. Do not re-walk the full suite after every small fix.

Pre-existing breakage within the requested journey still makes its verdict FAIL.
When authorized to fix it, the defect becomes the next action. Otherwise,
escalate the specific decision or effect and continue independent authorized
work. A review-only request authorizes reporting defects, not implementation.
Keep delta-first PR findings separate from the full workflow's verdict.

## Preserve boundaries

User screenshots, recordings, and errors are primary evidence. Inspect them
through supported tools. Diagnose recoverable access or format failures, but
never bypass a safety-hook block, sandbox, guardian, DLP, or browser quarantine.
Record the specific unmeasured evidence and continue independent work when a
hard boundary prevents inspection.

For browser work, authentication, seeded identities, manual login handoffs, or
QA publication, load `verified-qa-e2e` and pass its applicable deterministic gate.
Use only the authorized isolated browser, keep page ownership, and obtain the
required input-isolation proof. Never use a live mail client to test sending,
handle credentials, expose a local service, or mutate production merely to
complete a test. User authorization and hard prohibitions still govern actions.

## Report precisely

Name persona, target identity, user outcomes attempted, and each verdict. Attach
command or interaction, expected result, observed result, and a findable artifact
at the relevant evidence tier. Distinguish proposed, implemented, installed,
and exercised outcomes. Correct prior unsupported claims explicitly. Missing
evidence is NOT RUN; honest partial evidence is useful and must not be hidden.
