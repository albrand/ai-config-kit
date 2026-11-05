# GitHub Actions integration

Use the complete starter at `templates/qa-kit/ci/github-actions.yml` as a workflow skeleton, then adapt checkout identities, exact runner commands, artifact URLs and deployment commands. Keep tokens out of the plan and test jobs. GitHub Actions draft PRs may be suppressed by workflow conditions or repository policy; test a ready-for-review PR explicitly.

## App repository PR workflow

1. `plan`: checkout the PR head and QA authority at its protected default branch; resolve linked work items, already-delivered items and base-scenario regressions. Upload a versioned plan artifact.
2. `test`: checkout the same PR head, overlay QA-authoritative scenarios/tests, report ignored branch copies, and run the complete suite. Give the process `contents: read` only; do not pass board, upload, deployment or write tokens. Upload runner JSON/XML, TRX, Allure results and screenshots even on failure.
3. `judge`: always runs after test; compare plan scope with compile/discovery/execution evidence and base membership. Write one row for each linked/related/regression scenario, including skipped and not-run reasons. The job exits nonzero for FAILED/BLOCKED.
4. `report`: generate Markdown + HTML + Allure single-file output. Publish all evidence as an access-controlled artifact first. Only after artifact confirmation, use a separate job with the narrow board token to post the content-hash-idempotent summary and ticket link. Missing artifact URL, token or board confirmation keeps verdict BLOCKED.
5. Protect the app default branch: require this workflow's stable check name, require branches current, block merge when failing, and require PR review. Do not assume `pull_request` builds draft PRs.

## QA repository PR workflow

Install a second workflow inside the QA-owned repo. Trigger `pull_request` for changes under scenario, test, schema, parser, gate and board paths. `checkout` with full history, install Node 22 (no dependencies required for the kit), compile the changed test projects, discover their scenario IDs, execute changed/new automated scenarios, parse native result files and run `check-scenarios --base origin/<target>`. Reject static evidence, comments/strings/dead code, `#if false`, skipped tests, mismatched IDs, and manual/awaiting entries missing the same required fields enforced by the app gate. `manual` / `awaiting` exceptions require review by the QA owner role. Require the workflow check and CODEOWNERS review on `qa/**`; app developers must not have write permission to the QA source.

## Release stages and tiers

Carry one candidate SHA and linked-work-item set unchanged through protected GitHub Environments `DEV` → `STAGING` → `PROD`. Require approval on STAGING/PROD as policy dictates; run deployment smoke after DEV, full release tier after STAGING, and production sanity after PROD. Release promotion depends on green PR plan/test/judge/report and names the same SHA in every stage.

- Pre-push tier: changed work-item scenarios + relevant fast component tests, run locally before publishing a branch.
- PR tier: all linked and related scenarios + full base regression set + API/browser smoke, token-free.
- Release tier: rerun candidate suite against deployed DEV/STAGING/PROD endpoints, capture screenshots/Allure and verify ticket/report links.

Set repository Settings → Rules → Rulesets (or Branches → Branch protection rules) for the default/release branches. Add the workflow's exact check name as required, require PRs and approvals, disable force pushes/deletions, require status checks before merge, and check “Require branches to be up to date.” In Settings → Environments, create DEV, STAGING, PROD and attach environment secrets only to deploy/report jobs that need them. Protect the QA repository with a separate required QA check and CODEOWNERS.

The starter template uses example repository names and placeholder scripts. Replace those values before enabling `--apply`; request payloads are covered offline by unit tests.
