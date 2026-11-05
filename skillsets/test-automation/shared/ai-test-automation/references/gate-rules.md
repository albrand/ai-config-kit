# Gate rules

| Evidence | Verdict | Blocks? |
|---|---|---|
| Passed executed automated test | VERIFIED | no |
| Failed executed test | FAILED | yes |
| Missing or invalid required evidence | BLOCKED | yes |
| Approved manual/awaiting exception with required fields | NOT_APPLICABLE | policy-dependent |
| Draft scenario | DRAFT_PASSED | no merge approval implied |

New scenarios need compile + discovery + execution evidence. Skipped tests are not executed. Regression membership is computed from base scenario set, not head. Every in-scope row appears with a result/reason. Executed browser scenario requires screenshot; attachment failure blocks. Test job receives no secrets and installs QA-owned tests over branch copies. Report-only changes preserve verdict bytes.
