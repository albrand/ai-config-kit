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

Falsification: the selected evidence must be able to fail for the right
reason. Apply the defect-check and persistence-readback rules in
`DELIVERY_QUALITY.md`; a check that survives the seeded defect provides no
evidence for the claim it is meant to cover.

For material changes to instructions that control agent behavior, also run a
few fresh, bounded task trials against raw artifacts. Compare the previous
instructions when available, include a valid small-change counterexample,
and keep the evaluator's expected diagnosis out of the task brief. Inspect
actions and evidence, not just the final wording; structural checks alone
cannot establish better delivery or a measured reliability improvement.
