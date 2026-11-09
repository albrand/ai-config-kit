---
name: qa-bug-hunting-test-automation
description: Bind automated tests to scenarios; specific asserts; fail-first proof; mocks must not encode answers.
---

# Bug-hunting test automation

Read: parent skill **First principle** and `references/gate-rules.md`.

## Priority

1. Assert every `expected` line with a specific matcher (not truthy, not “any svg”).
2. Red when the criterion is broken; green when met; new tests red on merge base.
3. Cover positive, negative, regression per criterion.
4. Mocks OK — return mixed data; the app under test performs filter/empty-state logic.
5. Product bugs stay red (`status: bug`).

## Automation

- One test per automated scenario; `scenario_id` label required.
- Do not copy expectations from component implementation; copy from scenario `expected` only.
- Optional: fail unhandled mock calls so empty accidental responses cannot green empty-state tests.
