---
name: ai-test-automation
description: Set up test automation, a QA gate, Allure reporting, scenarios from tickets, or board integration.
---

# AI-assisted test automation

Use this skill to build a QA-owned scenario system whose source of truth stays separate from application changes. The starter kit uses Node built-ins only and runs on Node 22+; runner-specific Allure packages belong in the application repository.

## Quick start (30 minutes)

1. Copy `templates/qa-kit/` into a QA-owned repository as `qa/`; `cd qa`; copy `qa.config.example.json` to `qa.config.json`.
2. Fill `board`, `boardUrl`, `repo` if applicable, `boardTokenEnv`, `base`, `scenarioFile`, `resultsFile`, `authoritativePaths`, and `testCommand`. Put the token only in a CI secret named by `boardTokenEnv`.
3. Preview a board read: `node bin/qa.mjs board read WI-123 --config qa.config.json --dry-run`. Expected: JSON `mode: "dry-run"`, GET URL and request shape; no `fetch` call is made and no credential value is printed.
4. Add a starter scenario set and executed run evidence, then run `node bin/qa.mjs check-scenarios --head scenarios.json --base origin/main --file scenarios.json --results run-v1.json`. Expected: JSON rows for new/changed/deleted IDs; exit 0 only when every changed automated case compiled, was discovered and executed, and exception records are valid.
5. Run `node bin/qa.mjs judge --scenarios scenarios.json --results run-v1.json --base-scenarios base-scenarios.json`. Expected: one verdict row per head/base scenario; any missing/skipped/failed evidence exits nonzero.
6. Copy and adapt `ci/github-actions.yml` or `ci/azure-pipelines.yml`, wire the app PR gate and QA-repo validation, and make both checks required. Run the negative probes in phase 10 before enabling writes.

## 0. Decide

Record answers and accountable owners in `qa/README.md` before changing permissions or CI.

| Questionnaire | Answer | Decision driven by that answer |
|---|---|---|
| Which board/workspace/project, item types, IDs and query scope are authoritative? | `…` | Adapter, read fields, revision and linked-item discovery |
| Which CI host, default branch, protected branches and draft policy apply? | `…` | Workflow template and exact required-check name |
| Which app repos are in scope, and will QA authority live in a separate repo or protected directory? | `…` | Checkout topology and write boundary |
| Which languages/runners, compile/discovery commands and result formats exist? | `…` | Parser, runner binding and test tier commands |
| Which QA role approves scenario changes and exception records? | `…` | CODEOWNERS, ACL and approval artifact |
| Which environments exist, and who approves DEV/STAGING/PROD promotion? | `…` | Release stages and environment protections |
| What may screenshots/reports contain, who can read them, and when are they deleted? | `…` | Redaction, artifact visibility and retention |
| What are provider limits, retry budget and conflict behavior? | `…` | Adapter timeouts, throttling and reconciliation |

- Create `qa/README.md`, `qa/qa.config.json`, decision/ownership table, and secret-name list (never secret values).
- Check: `node -e "const c=require('./qa/qa.config.json');if(!c.board||!c.base||!Array.isArray(c.authoritativePaths)||!c.boardTokenEnv)process.exit(1);console.log('configuration shape: PASS')"` → `configuration shape: PASS` and exit 0; each row above has an answer or named blocker.
- Prevents: selecting authority, release scope or a token path by guesswork.

## 1. Isolate QA ownership

Prefer a separate QA repository. Otherwise protect `qa/**` using CODEOWNERS and branch policies. Create a least-privilege agent identity: read app code and board context, read QA definitions, open a QA PR, and write reports only through the approved reporter. Do not grant merge/bypass access. For GitHub use a read-only app installation on the QA repository plus scoped issue/report permissions in a separate job; Azure DevOps use repo ACL and build identity scopes; Jira/Linear use dedicated bot identities scoped to the needed project/team. Verify effective permissions because a broad-group Deny can override a narrower Allow. A required PR policy can also block direct push, so the agent path must create a PR or have an explicitly permitted route.

- Create `.github/CODEOWNERS` or host equivalent, required QA-review/build policies, identity record and a read/write permission matrix.
- Check: use host ACL inspection (GitHub `gh api repos/OWNER/REPO/collaborators/USER/permission`; Azure project/repo permissions UI/API; Jira project permissions; Linear team membership) and test the intended identity can open a PR but cannot bypass review. Save sanitized output in `qa/rollout-verdict.md`; expected: read allowed, QA write via reviewed PR only, bypass denied.
- Prevents: developers modifying their own acceptance tests and brittle direct-push automation.

## 2. Add the board adapter

Choose `jira`, `azure`, `linear` or `github`; otherwise implement the interface in `references/board-adapters.md`. Implement read with revision, comment, attach, transition/move, PR link and signed webhook validation. Prefer MCP for interactive human reads; use REST/GraphQL with an explicit service identity for reproducible CI. Keep all writes dry-run unless `--apply` is passed. Use an item + commit + normalized-content-hash marker for comments and bounded retries.

- Create `qa.config.json`, `lib/boards/<board>.mjs`, webhook verifier and request fixtures. Reference exact auth/env names in `references/board-adapters.md`.
- Check: `node --test test/*.test.mjs` → adapter request-shape tests pass with zero live requests; `node bin/qa.mjs board read WI-123 --dry-run` → request printed, mode dry-run, no authorization secret visible.
- Prevents: stale updates, duplicate comments, accidental writes and spoofed events.

## 3. Define and refine scenarios

Use `references/scenario-schema.md` and version every artifact: work-item snapshot, scenario-set, approval, plan, run, verdict. Scenario ID: stable `QAS-<work-item>-<nn>`; criteria ID: `AC-<stable-name>`. Every scenario records kind `automated|manual|awaiting`, surface `api|browser`, `mandatory`, title, steps and expected result. Manual requires owner, procedure and reason. Awaiting requires owner, reason and revisit date. AI refinement may return only READY, NEEDS_CLARIFICATION or REJECTED; it cannot approve. Ask focused questions for ambiguity, keep source links/revision, never add unsupported criteria, and summarize collateral effects: scope expansion/removal, privacy, browser surface and regression impact.

- Create `scenarios/v1/<item>.json`, `approvals/v1/<item>.json`, schema fixtures and a refinement prompt with the allowed response contract.
- Check: `node bin/qa.mjs check-scenarios --head scenarios.json --base origin/main --file scenarios.json --results run-v1.json` → every new/changed row shows `ok:true`; malformed IDs, changed-same-ID content without evidence, removed IDs and invalid exception records fail.
- Prevents: criteria drift, silent coverage loss and AI self-approval.

## 4. Generate and bind tests

Use one deterministic test binding per automated scenario. Build/compile and test discovery must produce machine-readable evidence. Add Allure custom label `scenario_id` and keep a native runner result file. Follow `references/allure.md` for Playwright, Vitest, Jest, pytest, xUnit, NUnit or JUnit 5. A test title or source string alone is never evidence.

- Create test source, runner config, `allure-results/`, native result output and `run-v1.json` containing compiled=true, discovered IDs, executed status and screenshot evidence.
- Check: run the actual compile, discovery and test commands; `node -e "const r=require('./run-v1.json');if(r.compiled!==true||!r.discoveredIds?.length)process.exit(1);console.log('compile/discovery evidence: PASS')"` → PASS. Parse results and require exact ID/status.
- Prevents: comments, literals, disabled tests, skipped tests and unrelated tests impersonating coverage.

## 5. Enforce QA storage rules

A new or changed automated scenario is stored only after compile + discover + execute evidence. Skips do not count. Manual and awaiting exceptions use the same validation function and fixtures in storage and gate; exceptions are reviewed and include their required owner/reason/procedure or revisit date.

- Create a QA PR workflow running `node bin/qa.mjs check-scenarios --head scenarios.json --base origin/main --file scenarios.json --results run-v1.json` and CODEOWNERS approval.
- Check: run the same fixture set through storage validation and `judge`; expected verdicts match exactly for valid/invalid manual and awaiting examples, skipped tests, missing evidence and malformed scenario content.
- Prevents: compiling no tests, unexecuted tests, or exception-policy drift.

## 6. Build the gate

Split gate into plan/test/judge/report. The planner gets write targets only from `linkedItemsForChange(change)` on the board/forge; title, body, branch and `--item` values are hints only. Keep all current scenarios and every base regression in gate scope, even when their tickets are not associated with this change. Those scenarios cannot create board writes unless their item is independently associated. Test overlays QA-owned tests over branch copies and reports ignored copies; it gets no board, artifact-write or deployment secret. Judge evaluates every in-scope scenario and records result, reason, source evidence, screenshot or not-run reason. Missing executed evidence, screenshot, token, upload confirmation or attachment blocks.

- Create versioned plan/run/verdict JSON, authoritative overlay, token-free test step and report artifact.
- Check: use fixtures to confirm one row per planned ID including deleted base IDs; skipped → BLOCKED; failed → FAILED; missing browser screenshot/token/upload receipt/attachment → BLOCKED. Expected: judge exit 1 for each blocker.
- Prevents: false-green PRs, dropped regressions and unsupported success claims.

## 7. Publish Allure

Install the selected adapter in the application repo, emit `scenario_id`, generate Allure 3 single-file HTML grouped by sprint/feature/scenario, and upload raw result files plus screenshots as CI artifacts. Render a pending report, publish it, post item summaries and capture receipts, then render the final report with `--post-receipt`; an unconfirmed post leaves every row BLOCKED. Keep retention and visibility aligned with report data sensitivity.

- Create runner config, `allurerc.mjs`, report command, artifact upload and ticket-link operation.
- Check: inspect a sample artifact and verify IDs, status and screenshot attachment; check report URL returns to the authorized QA persona. Expected: artifact upload receipt + ticket link receipt; otherwise BLOCKED.
- Prevents: evidence that is missing, untraceable or linked before publication.

## 8. Wire CI and release tiers

Use `references/ci-github-actions.md` or `references/ci-azure-pipelines.md`. Install app PR gate and QA-repo PR validation separately. Require both checks; draft PRs are not validation evidence. Keep tiers: pre-push (changed scenarios + fast components), PR (linked/related + full base regressions + smoke), release (candidate rerun plus deployed environment sanity). Carry the same candidate SHA and ticket set DEV → STAGING → PROD with approvals.

- Create app and QA workflows, named required checks, environment rules, artifacts and least-privilege job scopes.
- Check: open a ready-for-review probe PR and a QA scenario PR; expected required checks appear and block merge when failing, while test job has no board token. Run one release dry-run and compare candidate SHA across all stages.
- Prevents: draft-only validation, unprotected QA authority and release drift.

## 9. Log board events and move work items

Record consistent steps: refine, approve, plan, test, judge, report, release. Comments use marker `work-item + commit + content hash`; an identical replay is a no-op, while revised content gets a different marker. Upload before linking, link before moving status, and transition only after a green verdict plus confirmed report. Verify webhook signatures on raw bytes before queueing.

- Create event-to-state map, signed webhook handler, dedupe key and stale-revision policy.
- Check: replay same signed event twice and expect one comment/link/transition; change report content on same commit and expect a new hash; stale revision, failed upload and bad signature produce no success transition.
- Prevents: duplicated history, spoofed events and cards moved before evidence is ready.

## 10. Prove the rollout on your board

Run probes in an isolated test project on the user's board; this is a procedure for the adopting team, not a prerequisite for publishing this skill. Include positive PR and negative probes for comments, regular/verbatim/raw/interpolated strings, `#if false`, `Skip=`, skipped result, removed and changed-same-ID scenarios, wrong ID, missing screenshot, failed attachment, missing token and missing upload confirmation. Run all corpus fixtures. Then walk one representative item through refinement, approval, CI, Allure artifact, report and board state.

- Create `qa/rollout-verdict.md` with persona, board/project, CI stack + candidate SHA, each user outcome, attempted input, expected and observed evidence, and verdict.
- Check: `node --test test/*.test.mjs` passes all rule cases; live probes show positive case VERIFIED and each negative case blocks for the stated reason. Any ambiguous probe is FAIL. A user running this skill should report one row per goal, e.g. `Persona | target + SHA | outcome | PASS/FAIL/BLOCKED | evidence`.
- Prevents: enabling a workflow based on a green unit suite without checking its real board/CI path.
