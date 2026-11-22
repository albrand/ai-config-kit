# P4 per-cluster fixes and batch lifecycle

## P4 Fix per cluster

One commit per cluster, its repro going red to green. After the fix, re-run
the cluster's repro and the focused tests covering the change. After 3 failed
attempts on one cluster, stop and escalate with the repro output.
## Batch lifecycle: one full re-walk after the inventory closes

Treat every defect found in one P1 walk as one batch. Do not run another full
QA walk after each fix PR. Fixes can land in parallel or sequentially on a
batch branch such as `qa/batch-<run>`; run the cluster repro and focused tests
for each fix, then close the corresponding inventory rows. A PR whose base is
not protected can merge while the batch inventory is open. PR merges are
never gated (owner decision 2026-10-06); a protected push and a production
deploy stay gated.

When the batch inventory has no open rows, run P5 once against the aggregate
batch head. Use Playwright coverage for as much of the workflow as is
automated. Each Playwright test that covers a workflow step carries this
annotation, where the workflow name matches both `workflow.json`'s
`workflow` and an entry in `.qa/config.json` `workflows[].name`:

```ts
testInfo.annotations.push({
  type: "qa-step",
  description: "invite-and-accept::accept",
});
```

Generate `.qa/rewalk.json` from the Playwright JSON report and the batch run's
`.qa/workflow.json`:

```sh
python3 <skill-dir>/scripts/rewalk-from-playwright.py \
  <playwright-report.json> .qa/workflow.json \
  --sha <batch-head-sha> --target <preview-url> \
  --deployment-id <deployment-id> --output .qa/rewalk.json
```

Each step is `PASS` only when every annotated test passed on its first
attempt. Failed, skipped, and flaky tests produce `FAIL`; retries do not turn
a failed first attempt into a pass. A step with no annotated test is
`NOT_AUTOMATED`. It still needs the visible manual walk represented by the
existing `claim_e2e_complete` evidence packet: add `workflow_step` with the
exact step name to the matching observed `journey.steps[]` entry and include
that entry's normal evidence. The ship gate runs the existing E2E evidence
checker and denies an unmapped `NOT_AUTOMATED` step without that manual
evidence.

The converter records the report path plus trace and screenshot attachment
paths on each covered step, along with the preview target and deployment id.
Commit the generated re-walk with the closed inventory and the batch head's
QA artifacts. The gate accepts that QA-only evidence commit immediately on
top of the walked batch head. PR merges are free; a push to a protected branch
(the default branch or `.qa/config.json` `protected_branches`) requires the
closed inventory and one current re-walk.
