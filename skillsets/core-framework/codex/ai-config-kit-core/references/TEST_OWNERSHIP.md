# Test Ownership

Require new test evidence only for behavior, contracts, and invariants the
repository owns. Select the smallest falsifiable evidence at the owning boundary.

- Do not recreate upstream library/vendor suites; test only the integration
  assumption the repository depends on.
- Validate declarative config with its native parser, linter, schema, or planner.
- Validate migrations by applied outcome, compatibility, and rollback/forward
  fix—not raw migration text or tool mechanics.
- Validate generated artifacts through generator parity and real consumers—not
  generated internals.
- Use reference, manifest, format, and encoding checks for docs and policies.
- Security-sensitive owned behavior requires durable automation: a test or CI
  guard.

This governs new validation and does not automatically delete existing tests.
Manual QA is valid for visual or one-shot outcomes, but it is not durable
protection for a high-risk owned invariant.
