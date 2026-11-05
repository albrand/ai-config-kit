# Pitfalls and checks

- Broad-group Deny overrides narrower Allow: inspect effective permissions.
- Required PR policy can block agent direct push: assert route guards and use PR.
- Draft PR may not trigger validation: verify non-draft required check.
- First cross-repo pipeline needs authorization: run authorization preflight.
- Test steps must be secret-free: inspect job environment and permissions.
- Branch copies can spoof authority: overwrite from QA source and report ignored copies.
- Regression set comes from base: mutate head only and assert prior scenarios remain in scope.
- Static test-exists checks are spoofable: compile, discover and execute; reject comments, dead code and skipped tests.
- Manual/awaiting rules must match storage and gate: run shared fixtures through both.
- Report-only edits must preserve verdict bytes: compare canonical verdict output.
- Failed attachment blocks: inject attachment failure.
- Repeated CLI args accumulate: assert multiple `--item` values retained.
- Tracker comments are idempotent by commit: replay same operation twice.
