---
name: qa-bug-report
description: Record a found defect as a red scenario with bugKey; block only that ticket's PRs.
---

# Bug report

Read: `references/gate-rules.md` (BUG verdict) and `references/scenario-schema.md` (`status`, `bugKey`).

## When a test is red and the product is wrong

1. Open or link a board defect; capture its id as `bugKey`.
2. Set on the scenario: `"status": "bug"`, `"bugKey": "<id>"`, keep steps/expected as the correct behaviour.
3. Leave the automation **failing** until the fix ships; do not weaken `expected`.
4. `judge` reports `BUG` for that scenario; it **blocks** only PRs whose plan links the same work item.
5. After the fix, remove `status: bug`, run full proof, and return the scenario to normal gate.
