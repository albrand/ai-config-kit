---
name: qa-bug-report
description: Record a found defect as a red scenario with bugKey; block only that ticket's PRs.
---

# Bug report

Read: `references/gate-rules.md` (BUG verdict) and `references/scenario-schema.md` (`status`, `bugKey`).

## When a test is red and the product is wrong

A scenario-faithful test is red and the ticket, its acceptance criteria or its design reference say the app should behave differently. Visual mismatches count: letter case, colour, background, font family, font size, font weight, icon.

1. Open or link a board defect; capture its id as `bugKey`.
2. Set on the scenario: `"status": "bug"`, `"bugKey": "<id>"`, keep steps/expected as the correct behaviour.
3. Leave the automation **failing** until the fix ships; do not weaken `expected`.
4. `judge` reports `BUG` for that scenario; it **blocks** only PRs whose plan links the same work item.
5. After the fix, remove `status: bug`, run full proof, and return the scenario to normal gate. The bug is closed only when the same, unchanged test is green on the fix.

## What the defect record contains

- Repro steps, the QAS id, **expected** quoted from the ticket, acceptance criterion or design reference with its source, and **actual** (what the app shows).
- For a visual mismatch, list expected and actual for each property: copy in its letter case, colour, background, font family, font size, font weight, icon.

## Never

- Write the **observed** app value as the expected value, or quote application source as the source of expected.
- Loosen a matcher (case-insensitive regex, partial match, `toBeVisible()`, count above 0) so the test passes.
- Add `skip`, `fixme`, `test.fail`, an inverted assertion, a retry or a longer timeout to hide the red.
- Treat `--allow-draft-pass` or one green local run as proof the bug is gone.
- Withdraw a bug unless the ticket text does not require the behaviour; cite that ticket line in the record. A test defect (missing stub, wrong fixture, a mock that refused a write the scenario never declared) is fixed without weakening any assertion.
