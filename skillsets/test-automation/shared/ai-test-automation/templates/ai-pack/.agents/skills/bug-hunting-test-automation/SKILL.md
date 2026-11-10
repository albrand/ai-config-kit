---
name: qa-bug-hunting-test-automation
description: Bind automated tests to scenarios; specific asserts; fail-first proof; mocks must not encode answers.
---

# Bug-hunting test automation

Read: parent skill **First principle** and `references/gate-rules.md`.

## Priority

1. Assert every `expected` line with rendered text (exact, case-sensitive—CSS `text-transform` counts), computed colour, background, font family, font size, font weight, and named icon identity; visibility alone never satisfies a line.
2. Red when the criterion is broken; green when met; new tests red on merge base.
3. Cover positive, negative, regression per criterion.
4. Mocks OK — return mixed data; the app under test performs filter/empty-state logic.
5. Product bugs stay red (`status: bug`).

## Automation

- One test per automated scenario; `scenario_id` label required.
- Do not copy expectations from component implementation; copy from scenario `expected` only.
- Optional: fail unhandled mock calls so empty accidental responses cannot green empty-state tests.
- Proof: for each visual value the scenario names, set it deliberately wrong and confirm the test fails on that assertion (not merely because the feature is missing).
- `node qa/bin/qa.mjs check-scenarios --source` enforces Playwright/Testing Library `getByText`/`getByLabelText` with `{ exact: true }`, bans case-insensitive text matchers, and rejects visibility-only binding.
