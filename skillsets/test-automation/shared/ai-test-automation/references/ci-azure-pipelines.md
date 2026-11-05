# Azure Pipelines integration

Start with `templates/qa-kit/ci/azure-pipelines.yml` and adapt its `resources.repositories`, service connections, actual test invocation, artifact URL capture and deployment scripts. A first cross-repository checkout usually pauses for repository authorization: authorize the QA repository explicitly before relying on its files. Never place board credentials in the token-free test stage.

## Application PR pipeline

1. Declare the QA repository as a protected repository resource pinned to its default branch, with read-only pipeline permission. Verify the first pipeline run is authorized.
2. Plan linked and delivered work items and base regressions; publish the plan artifact.
3. In a separate job, checkout the PR head plus QA authority, overwrite branch copies, print ignored paths, and run the full suite with board/upload secrets unset. Publish runner output, screenshots and Allure results even after failure.
4. Always run `judge` against the merge base. It emits all linked, related and regression rows, including skips and not-run reasons. A missing screenshot, artifact confirmation or upload confirmation is BLOCKED.
5. Publish Markdown/HTML and single-file Allure as an access-controlled pipeline artifact. Only after success, run a separate board-report stage with a scoped variable group; post with an item+commit+content hash marker and verify the API receipt. A report that was not posted remains BLOCKED.
6. In Project Settings → Repositories → Policies, add a Build validation policy for the app target branch; set it required, automatic, and apply to the intended paths. Add required reviewer policies. Do not use a draft PR as proof that build validation runs.

## QA repository validation

Place `templates/qa-kit/ci/qa-repository-pr-azure.yml` in the QA repository as its separate PR pipeline and require it on scenario/test paths. It fetches the target branch, compiles the changed runner projects, discovers IDs from runner output, executes the configured suite, parses native result artifacts, and rejects static-only or skipped evidence. Add a QA-owner reviewer policy for schema/scenario changes. The storage validator and application judge must share fixtures and exception-field rules so manual/awaiting behavior cannot diverge.

## Release stages and tiers

Promote the exact tested candidate SHA and work-item set through deployment jobs with environments `DEV`, `STAGING`, `PROD`. Configure approvals/checks on STAGING and PROD, pin artifact version, and make later stages depend on successful earlier stages. Run pre-push changed-scenario tests; PR linked+related+base-regression tests; release candidate tests and deployed smoke/sanity walks. Every stage uploads evidence and links it only after artifact confirmation.

Configure pipeline variables/secrets by stage and scope them only to report/deploy jobs; keep test job variables explicitly empty for board tokens and upload credentials. Set a required build-validation policy using the pipeline's stable definition name and “Policy requirement: Required”. Add QA repo read authorization explicitly; do not give application contributors write access to authoritative scenarios.
