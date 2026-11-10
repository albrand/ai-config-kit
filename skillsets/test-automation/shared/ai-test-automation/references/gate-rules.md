# Gate verdicts and blocking rules

## Behaviour-first gate (always on)

- `check-scenarios` rejects designs drafted from implementation paths, vague `expected` lines, mocks that encode the answer, missing `mockPolicy` when steps use mocks, missing positive/negative/regression coverage per criterion, steps or expected that cite code, vacuous automation (`toBeTruthy`, `expect(true)`), mocks that pre-filter in source, and `--source` files that omit an `expected` line from executable assertions. A line counts only inside `expect(…).matcher` (or runner `Assert.*` / `assert`); bare `getBy*` queries never count. Visibility-only matchers never satisfy an `expected` line. `--source` rejects case-insensitive text handling (including `.toLowerCase()` / `OrdinalIgnoreCase` / `re.I`), partial substring matchers (`in`, `Assert.Contains`, `.includes`, `toContainText`, `re.search`, …), and Playwright/Testing Library string `getByText` / `getByLabelText` without `{ exact: true }` on **every** text locator in the file (including assignments passed to `expect` later). Equality only for quoted copy: `toHaveText('…')`, `Assert.Equal`, `assert ==`, `assert.strictEqual`. Visual `expected` lines are detected when they name a colour value (`#hex`, `rgb`), font family, font size with a unit, font weight, or letter case; they require `toHaveCSS` / `toHaveStyle` / `getComputedStyle` (or documented runner equivalent), not text, visibility, or `toHaveClass` alone. Runners covered: Playwright, Testing Library, xUnit `Assert.Equal`, Node `assert.strictEqual`, pytest `assert ==`. Assertion shapes are found on tokenized source; literals are read from the original file only inside detected calls.
- `judge` accepts optional `--base-results <run-v1.json>`; any **new** scenario that **passed** on the merge base is `BLOCKED` with reason `passes without the change`.
- Scenarios with `status: bug` and a linked `bugKey` stay red as `BUG`; they block only PRs whose plan links the same work item.
- With binding `draft`, the AI never self-approves: gate `DRAFT_PASSED` means tests pass and no blocking finding is open, then hand off to QA. `--allow-draft-pass` is only for local exit code 0; merge verdict is the gate without that flag after QA sets binding `ready`.

| Condition | Verdict | Blocking | Required explanation/evidence |
|---|---|---:|---|
| Automated scenario compiled, discovered, executed and passed; ID matches plan | VERIFIED | no | Runner result ID, outcome and execution record |
| Executed automated test failed | FAILED | yes | Native failure/result reference |
| Test was skipped, not discovered, not executed, or has only source text | BLOCKED | yes | Explicit skip/not-run reason |
| Missing compile or discovery evidence for new/changed stored scenario | BLOCKED | yes | Missing stage name |
| Required scenario was deleted from head but existed at base | BLOCKED | yes | `base scenario removed from head`; reviewed disposition required |
| New/changed scenario passed all evidence and approval rules | VERIFIED | no | Scenario content hash, run and approval reference |
| Valid reviewed manual exception | NOT_APPLICABLE | no | Owner, procedure and reason |
| Valid reviewed awaiting exception | NOT_APPLICABLE | no | Owner, reason and revisit date |
| Manual/awaiting record missing required fields or approval | BLOCKED | yes | Missing fields/approval |
| Draft scenario with explicit human approval pending | DRAFT_PASSED | no merge approval implied | Draft marker and reviewer state; AI hand-off only (see run-and-gate skill) |
| Known product bug on the scenario work item (status `bug`) | BUG | yes on that work item's PR only | `bugKey`, executed failure evidence |
| New scenario passed on merge-base run | BLOCKED | yes | `passes without the change` |
| Executed browser scenario lacks screenshot attachment | BLOCKED | yes | Screenshot missing |
| Artifact token missing, upload failed, URL absent or receipt unconfirmed | BLOCKED | yes | Attachment failure reason |
| Board report/link post has no positive API receipt | BLOCKED | yes | Report not posted |
| Invalid webhook signature, stale revision, or failed transition | BLOCKED | yes | Reject and do not move item |
| Branch copied acceptance test differs from QA authority | Branch copy ignored | n/a | Log the ignored path and run authoritative copy |
| Report-only edit changes the verdict table | BLOCKED | yes | Canonical reference-judge comparison must be byte-identical |

## Scope and evidence rules

- The plan keeps board write targets separate from gate scope. Only work items returned by `linkedItemsForChange(change)` may receive writes; every current scenario and every base scenario remains in `scenarioIds`, and every base scenario remains in `regressionIds` even when its work item is not linked to this change. Never derive regression membership from a head-side list or narrow it to currently associated tickets.
- Every in-scope scenario appears exactly once in the report, including no-result scenarios. Each row includes item, linked/related/regression scope, ID, verdict, reason, screenshot cell and not-run reason where relevant.
- Publish Allure assets as display-only data. The trusted publisher recomputes verdicts with `publish-evidence --plan <trusted-plan> --results <raw-run> --apply --receipt-output`; it does not accept verdict files from a PR report job. The final report marks every row BLOCKED unless every in-scope work item has a positive post receipt; `--posted` is not an accepted substitute.
- The test process gets no board, artifact-write or deployment secrets. An upstream checkout token is scoped to the checkout action with persisted credentials disabled.
- QA-owned definitions/tests overlay branch copies before execution. The report names every ignored branch path.
- Storage validation and gate validation use the same exception validators and fixtures.
- A successful upload means the provider returned a durable URL/ID and the board relation/comment write returned success. A prepared request is not confirmation.
- Verdict bytes are deterministic from plan + run evidence; report formatting, posting and presentation do not mutate verdict decisions.
- Attachments are required to pass when the scenario surface is browser and it executed. A screenshot URL is checked for presence and upload confirmation; raw bytes remain in protected artifact storage.
- Any required row with FAILED or BLOCKED makes the aggregate non-green; a skipped/not-run test never becomes VERIFIED.

## Reference judge

Keep one golden verdict fixture and run both the ordinary judge and report-only path against it. Compare canonical JSON bytes after key ordering. The fixture includes base regression, deleted scenario, manual, awaiting, skipped, failed browser without screenshot, missing token, failed upload, and successful attachment. A reporting-only change must preserve exact verdict bytes; if it does not, fail the gate and review a deliberate rule change separately.
