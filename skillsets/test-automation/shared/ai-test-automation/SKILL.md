---
name: ai-test-automation
description: Set up test automation, a QA gate, Allure reporting, scenarios from tickets, or board integration.
---

# AI-assisted test automation

Use this procedure to install a repeatable QA-owned gate. Keep board writes dry-run until explicitly enabled by an operator.

## 0. Decide

Ask: Which board/project? Which CI host? Which runners/languages? Separate QA repository or protected path? Who approves scenarios and board writes? Which release stages and data-retention limits apply?
- Create: `qa.config.json`, a short ADR and responsibility map.
- Acceptance: each question has an owner/answer or explicit dependency; trace one ticket through test and report.
- Prevents: hidden ownership and release assumptions.

## 1. Isolate QA ownership

Use a separate QA repository where application developers cannot alter authoritative tests, or a protected path with CODEOWNERS and required review. Create a dedicated agent identity. GitHub: protect branch/path and require QA review. Azure Repos: set explicit repo ACLs and branch policies. Check effective permissions: broad-group Deny can override narrower Allow. Guard direct push routes in code when policy requires PRs.
- Create: repository/path protection, identity, and permission smoke check.
- Acceptance: identity can read/open intended PR but cannot modify authoritative tests or bypass checks.
- Prevents: test-authority compromise and policy bypass.

## 2. Board adapter

Implement read item + revision, comment, attach artifact, transition, link PR, and receive event. Prefer board MCP for interactive reads; REST adapter for deterministic automation. Writes default to dry-run; require `--apply`. Include revision/ETag checks, bounded retries, rate limits and idempotency keys.
- Create: adapter per `references/board-adapters.md`, config, webhook signature validation.
- Acceptance: offline tests assert method/URL/headers/body; stale revisions fail; duplicate idempotency keys do not duplicate effects.
- Prevents: overwrites, duplicate comments and accidental writes.

## 3. Scenario model and AI refinement

Use `references/scenario-schema.md`. IDs are `QAS-<work-item>-<nn>`; criteria IDs map to explicit acceptance criteria. Classify automated/manual/awaiting (awaiting needs a reason), `surface` api|browser, and `mandatory`. AI proposes; a human approves. Verdicts: READY, NEEDS_CLARIFICATION, REJECTED. Record scope changes, removed coverage, privacy exposure and regression impacts.
- Create: versioned scenario snapshots, constrained prompt, approval history.
- Acceptance: schema validates; every criterion is covered or dispositioned; approval is attributable.
- Prevents: ambiguous, untraceable or self-approved coverage.

## 4. Generate and bind tests

Each automated scenario maps to a runner test with exact scenario ID metadata. Allure results carry `scenario_id`; see runner recipes in `references/allure.md`.
- Create: test, naming contract, label and parser fixture.
- Acceptance: compile, discover, execute and parse pass/fail samples bound to same ID.
- Prevents: string-only or orphaned tests.

## 5. Storage rule

New automated scenarios require compiled, discovered, executed evidence. Manual scenarios need owner, procedure and review. Awaiting needs reason, owner and revisit date. Storage validator and gate apply identical rules.
- Create: QA PR validator and exception schema.
- Acceptance: missing, skipped or malformed cases fail; valid exceptions are treated consistently.
- Prevents: untested scenarios and exception drift.

## 6. Gate

Implement plan/test/judge. Plan inventories linked and already-delivered items. Test installs authoritative QA tests over branch copies and runs without secrets. Judge lists every in-scope scenario, verdict, blocker, regression from merge base and not-run reason. Every executed browser scenario needs screenshot evidence. See `references/gate-rules.md`.
- Create: gate CLI, token-free test job, base comparison and artifact collection.
- Acceptance: fixtures prove expected verdicts; incomplete inventory, skipped test, failed attachment and missing screenshot block.
- Prevents: false green builds and hidden regressions.

## 7. Allure

Install the runner adapter in the application repo, attach labels and publish single-file HTML as a CI artifact; link artifact from the work item.
- Create: runner config, report generation/upload and ticket link.
- Acceptance: report ties each executed scenario and outcome to evidence and is downloadable from CI.
- Prevents: unfindable or untraceable evidence.

## 8. CI wiring

Wire application PR gate and QA-repository scenario check; require protected-branch policies. Draft PRs may not trigger validation. Release stages carry linked items through DEV/STAGING/PROD. Use pre-push, PR and release tiers. Templates in CI references.
- Create: required checks, QA PR validation and release jobs.
- Acceptance: non-draft PR cannot merge without green gate; invalid QA change rejected; release preserves item links.
- Prevents: skipped validation and unprotected test paths.

## 9. Board logging and movement

Log each step with stable title and commit identity. Comments are idempotent by commit; attach reports and link PR before transition. Move only when configured gate condition is met.
- Create: event-to-step map and idempotent operations.
- Acceptance: event replay causes no duplicate comment/transition; failed attachment blocks success.
- Prevents: misleading status and noisy history.

## 10. Prove end to end

Run positive/negative probe PRs, spoof matrix (comment/string, dead code, skip, wrong ID), corpus tests and a live ticket walk. Follow ticket through CI, Allure, report and board record.
- Create: probe matrix and verdict report.
- Acceptance: each goal has persona, target SHA, outcome and PASS/FAIL/BLOCKED evidence; expected blockers block.
- Prevents: self-attested or incomplete rollout.
