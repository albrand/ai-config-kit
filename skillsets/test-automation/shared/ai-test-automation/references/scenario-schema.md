# Versioned QA artifact schemas

All files use JSON Schema draft 2020-12 semantics. Store each artifact with its `schemaVersion` and `kind`; reject unknown versions and additional fields at the boundary. Work-item snapshots contain behavior-relevant fields only; omit person names and volatile status/date data from requirement text.

Every automated scenario is behavioural, not implementation-driven:

- `polarity`: `positive` or `negative` (regression cases set `regressionCase: true`).
- `layer`: `e2e`, `api`, `unit`, or `component`. Mocked HTTP is allowed at any layer; bias is about intent, not “real backend”. List each write the scenario expects (method, path, body) in `steps`; the mock accepts those and refuses every other write.
- `mockPolicy`: `mixed-source` when steps use mocks/fixtures — mixed input, application logic must produce the filtered or empty outcome.
- `expected`: one specific observable outcome per line; automation must assert each line (no loose “any element” wording).
- Binding: an automated scenario is bound by a runnable test whose title (or `scenario_id` label) carries the whole scenario ID; a comment, an unrelated string or a skipped test does not bind it.
- `status: bug` with `bugKey` records a found defect; keep the automation red until the product fix ships.

## Artifact contracts

The executable JSON Schema is [`artifact-schema.v1.json`](../templates/qa-kit/lib/artifact-schema.v1.json); tests load this same file so the reference and runtime contract cannot drift.

## Complete examples

### `work-item/v1`

```json
{"kind":"work-item","schemaVersion":1,"id":"WI-123","revision":"17","title":"Create account","description":"A new account can be created and recovered.","criteria":[{"id":"AC-create","text":"A valid request creates one account."},{"id":"AC-duplicate","text":"A duplicate email is rejected without creating another account."}],"capturedAt":"2026-11-05T12:00:00Z","sourceUrl":"https://tracker.example.invalid/items/WI-123"}
```

### `scenario-set/v1`

```json
{"kind":"scenario-set","schemaVersion":1,"workItemId":"WI-123","workItemRevision":"17","contentHash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","scenarios":[{"id":"QAS-WI-123-01","criterionIds":["AC-create"],"kind":"automated","surface":"api","mandatory":true,"title":"Creates account","steps":["POST valid payload"],"expected":"One account is returned"},{"id":"QAS-WI-123-02","criterionIds":["AC-duplicate"],"kind":"manual","surface":"browser","mandatory":true,"title":"Duplicate is rejected","steps":["Create account","Submit same email again"],"expected":"Duplicate warning appears","owner":"qa","reason":"Manual confirmation pending browser fixture","procedure":"Follow steps in staging"}]}
```

### `approval/v1`

```json
{"kind":"approval","schemaVersion":1,"scenarioSetHash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","decision":"approved","reviewId":"review-456","reviewedAt":"2026-11-05T12:05:00Z","reviewerRole":"qa-approver","notes":"Criteria mapping checked"}
```

### `plan/v1`

```json
{"kind":"plan","schemaVersion":1,"baseSha":"0123456789abcdef0123456789abcdef01234567","headSha":"abcdef0123456789abcdef0123456789abcdef01","items":[{"id":"WI-123","revision":"17","relation":"linked","scenarioIds":["QAS-WI-123-01"]}],"scenarioIds":["QAS-WI-123-01","QAS-WI-100-01"],"regressionIds":["QAS-WI-100-01"],"scenarioWorkItems":[{"scenarioId":"QAS-WI-123-01","workItem":"WI-123"},{"scenarioId":"QAS-WI-100-01","workItem":"WI-100"}],"namedNotLinked":["WI-999"],"crossRepo":[],"policyReasons":[],"createdAt":"2026-11-05T12:10:00Z"}
```

### `run/v1`

```json
{"kind":"run","schemaVersion":1,"planHash":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","commitSha":"abcdef0123456789abcdef0123456789abcdef01","runner":"junit5","compiled":true,"discoveredIds":["QAS-WI-123-01"],"results":[{"scenarioId":"QAS-WI-123-01","status":"passed","executed":true,"durationMs":42,"evidence":["junit-results.xml#testcase-1"]}]}
```

### `verdict/v1`

```json
{"kind":"verdict","schemaVersion":1,"planHash":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","runHash":"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","commitSha":"abcdef0123456789abcdef0123456789abcdef01","overall":"PASS","gateReasons":[],"rows":[{"scenarioId":"QAS-WI-123-01","verdict":"VERIFIED","reason":"Executed and passed on planned SHA","blocking":false}],"createdAt":"2026-11-05T12:11:00Z"}
```

IDs are immutable; never recycle deleted IDs. Regression membership is computed from the base scenario set, never head-side status edits. Requirement snapshots and reports must not include personal names or secrets.
