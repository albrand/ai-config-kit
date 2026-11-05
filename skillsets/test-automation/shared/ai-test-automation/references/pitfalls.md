# Pitfalls and the check for each

| Failure learned | Required check before adoption |
|---|---|
| An explicit Deny on a broad group overrides a narrower group's Allow. | Inspect effective permission for the exact service identity after inheritance is broken; assert read allowed, reviewed PR allowed, direct bypass denied. |
| A required PR policy can block agent direct push unless it can bypass. | Exercise the guarded agent route and require it to create/reuse a PR; never infer direct-push permission from repo write access. |
| Draft PRs may not trigger build validation. | Open a ready-for-review probe PR and confirm the exact required check starts; draft state is not evidence. |
| First cross-repo pipeline run needs repository authorization. | Run a checkout-only authorization preflight and confirm QA repo ref is resolved before relying on its files. |
| Test steps must run without secrets. | Print the test job's effective env names/scopes in a safe audit and assert no board/upload/deploy token is present; checkout credentials are not persisted. |
| Branch copies of acceptance tests can be edited to spoof authority. | Overlay QA-owned scenarios/tests before running, log ignored copied paths, and assert the installed digest equals QA source. |
| Regression membership comes from base, not head. | Remove or relabel a base scenario in a probe PR and assert it remains in the plan/report. |
| Static “test exists” checks are spoofable by comments, strings, dead code, `#if false` and `Skip=`. | Run tokenizer corpus plus compile, discovery and actual execution checks; each spoof probe must fail as a test definition. |
| Skipped tests are not executed. | Feed JUnit skipped, TRX NotExecuted, Playwright skipped and Allure skipped fixtures; all must remain non-VERIFIED. |
| Manual/awaiting exceptions must be judged the same by storage and gate. | Send identical valid/invalid fixtures through both consumers and compare verdict plus reason. |
| Report-only changes must keep verdicts byte-identical. | Run reference-judge golden fixture before and after report changes and compare canonical verdict bytes. |
| A failed attachment still blocks. | Inject upload HTTP failure, missing token, absent returned URL and failed relation; verify no success verdict or transition. |
| Repeated CLI args must accumulate. | Invoke repeated `--item`, `--source` and `--file` and assert all values are retained in order. |
| Tracker comments must be idempotent by commit plus content, not commit alone. | Replay identical marker twice and verify one comment; change content on the same commit and verify a different full hash marker. |
| PR linking or card movement can race with a stale board revision. | Change revision between read and write; expect conflict and no retry/move until re-plan. |
| Webhook deliveries can be forged or duplicated. | Invalid signature and repeated delivery ID must enqueue/mutate nothing; valid raw-body signature is accepted once. |
