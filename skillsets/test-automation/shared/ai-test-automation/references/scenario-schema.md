# Versioned QA artifact schemas

All files use JSON Schema draft 2020-12 semantics. Store each artifact with its `schemaVersion` and `kind`; reject unknown versions and additional fields at the boundary. Work-item snapshots contain behavior-relevant fields only; omit person names and volatile status/date data from requirement text.

## Artifact contracts

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.invalid/qa-artifacts/v1.schema.json",
  "oneOf": [
    {"$ref":"#/$defs/workItem"}, {"$ref":"#/$defs/scenarioSet"},
    {"$ref":"#/$defs/approval"}, {"$ref":"#/$defs/plan"},
    {"$ref":"#/$defs/run"}, {"$ref":"#/$defs/verdict"}
  ],
  "$defs": {
    "scenario": {"type":"object","additionalProperties":false,"required":["id","criterionIds","kind","surface","mandatory","title","steps","expected"],"properties":{
      "id":{"type":"string","pattern":"^QAS-[A-Za-z0-9_-]+-[0-9]{2,}$"},
      "criterionIds":{"type":"array","minItems":1,"uniqueItems":true,"items":{"type":"string","pattern":"^AC-[A-Za-z0-9_-]+$"}},
      "kind":{"enum":["automated","manual","awaiting"]},"surface":{"enum":["api","browser"]},"mandatory":{"type":"boolean"},
      "title":{"type":"string","minLength":1},"steps":{"type":"array","minItems":1,"items":{"type":"string","minLength":1}},"expected":{"type":"string","minLength":1},
      "owner":{"type":"string","minLength":1},"reason":{"type":"string","minLength":1},"procedure":{"type":"string","minLength":1},"revisitDate":{"type":"string","format":"date"}
    },"allOf":[{"if":{"properties":{"kind":{"const":"manual"}}},"then":{"required":["owner","reason","procedure"]}},{"if":{"properties":{"kind":{"const":"awaiting"}}},"then":{"required":["owner","reason","revisitDate"]}}]},
    "workItem":{"type":"object","additionalProperties":false,"required":["kind","schemaVersion","id","revision","title","criteria","capturedAt"],"properties":{"kind":{"const":"work-item"},"schemaVersion":{"const":1},"id":{"type":"string","minLength":1},"revision":{"type":["string","integer"]},"title":{"type":"string"},"description":{"type":"string"},"criteria":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["id","text"],"properties":{"id":{"type":"string","pattern":"^AC-"},"text":{"type":"string","minLength":1}}}},"capturedAt":{"type":"string","format":"date-time"},"sourceUrl":{"type":"string","format":"uri"}}},
    "scenarioSet":{"type":"object","additionalProperties":false,"required":["kind","schemaVersion","workItemId","workItemRevision","scenarios"],"properties":{"kind":{"const":"scenario-set"},"schemaVersion":{"const":1},"workItemId":{"type":"string"},"workItemRevision":{"type":["string","integer"]},"scenarios":{"type":"array","items":{"$ref":"#/$defs/scenario"}},"contentHash":{"type":"string","pattern":"^sha256:[a-f0-9]{64}$"}}},
    "approval":{"type":"object","additionalProperties":false,"required":["kind","schemaVersion","scenarioSetHash","decision","reviewId","reviewedAt"],"properties":{"kind":{"const":"approval"},"schemaVersion":{"const":1},"scenarioSetHash":{"type":"string","pattern":"^sha256:[a-f0-9]{64}$"},"decision":{"enum":["approved","changes-requested","rejected"]},"reviewId":{"type":"string"},"reviewedAt":{"type":"string","format":"date-time"},"reviewerRole":{"type":"string"},"notes":{"type":"string"}}},
    "plan":{"type":"object","additionalProperties":false,"required":["kind","schemaVersion","baseSha","headSha","items","scenarioIds"],"properties":{"kind":{"const":"plan"},"schemaVersion":{"const":1},"baseSha":{"type":"string","pattern":"^[a-f0-9]{40}$"},"headSha":{"type":"string","pattern":"^[a-f0-9]{40}$"},"items":{"type":"array","items":{"type":"object","required":["id","revision","relation"],"properties":{"id":{"type":"string"},"revision":{"type":["string","integer"]},"relation":{"enum":["linked","related","regression"]}}}},"scenarioIds":{"type":"array","uniqueItems":true,"items":{"type":"string"}},"regressionIds":{"type":"array","uniqueItems":true,"items":{"type":"string"}},"createdAt":{"type":"string","format":"date-time"}}},
    "run":{"type":"object","additionalProperties":false,"required":["kind","schemaVersion","planHash","commitSha","runner","results"],"properties":{"kind":{"const":"run"},"schemaVersion":{"const":1},"planHash":{"type":"string","pattern":"^sha256:[a-f0-9]{64}$"},"commitSha":{"type":"string","pattern":"^[a-f0-9]{40}$"},"runner":{"type":"string"},"compiled":{"type":"boolean"},"discoveredIds":{"type":"array","uniqueItems":true,"items":{"type":"string"}},"results":{"type":"array","items":{"type":"object","required":["scenarioId","status","executed"],"properties":{"scenarioId":{"type":"string"},"status":{"enum":["passed","failed","skipped","not-run"]},"executed":{"type":"boolean"},"durationMs":{"type":"number","minimum":0},"screenshot":{"type":"string"},"evidence":{"type":"array","items":{"type":"string"}}}}},"processExitCode":{"type":"integer"},"sourceArtifacts":{"type":"array","items":{"type":"string"}}}},
    "verdict":{"type":"object","additionalProperties":false,"required":["kind","schemaVersion","planHash","runHash","rows","overall"],"properties":{"kind":{"const":"verdict"},"schemaVersion":{"const":1},"planHash":{"type":"string","pattern":"^sha256:[a-f0-9]{64}$"},"runHash":{"type":"string","pattern":"^sha256:[a-f0-9]{64}$"},"overall":{"enum":["PASS","FAIL","BLOCKED"]},"rows":{"type":"array","items":{"type":"object","required":["scenarioId","verdict","reason","blocking"],"properties":{"scenarioId":{"type":"string"},"verdict":{"enum":["VERIFIED","FAILED","BLOCKED","NOT_APPLICABLE","DRAFT_PASSED"]},"reason":{"type":"string"},"blocking":{"type":"boolean"},"screenshot":{"type":"string"},"notRunReason":{"type":"string"},"workItem":{"type":"string"},"scope":{"enum":["linked","related","regression"]},"linkedItems":{"type":"array","items":{"type":"string"}},"surface":{"enum":["api","browser"]},"executed":{"type":"boolean"}}}},"createdAt":{"type":"string","format":"date-time"}}}
  }
}
```

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
{"kind":"plan","schemaVersion":1,"baseSha":"0123456789abcdef0123456789abcdef01234567","headSha":"abcdef0123456789abcdef0123456789abcdef01","items":[{"id":"WI-123","revision":"17","relation":"linked"},{"id":"WI-100","revision":"9","relation":"regression"}],"scenarioIds":["QAS-WI-123-01","QAS-WI-100-01"],"createdAt":"2026-11-05T12:10:00Z"}
```

### `run/v1`

```json
{"kind":"run","schemaVersion":1,"planHash":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","commitSha":"abcdef0123456789abcdef0123456789abcdef01","runner":"junit5","compiled":true,"discoveredIds":["QAS-WI-123-01"],"results":[{"scenarioId":"QAS-WI-123-01","status":"passed","executed":true,"durationMs":42,"evidence":["junit-results.xml#testcase-1"]}]}
```

### `verdict/v1`

```json
{"kind":"verdict","schemaVersion":1,"planHash":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","runHash":"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","overall":"PASS","rows":[{"scenarioId":"QAS-WI-123-01","verdict":"VERIFIED","reason":"Executed and passed on planned SHA","blocking":false}],"createdAt":"2026-11-05T12:11:00Z"}
```

IDs are immutable; never recycle deleted IDs. Regression membership is computed from the base scenario set, never head-side status edits. Requirement snapshots and reports must not include personal names or secrets.
