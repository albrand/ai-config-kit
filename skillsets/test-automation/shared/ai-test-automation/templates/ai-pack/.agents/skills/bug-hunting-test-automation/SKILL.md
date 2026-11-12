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
4. Mocks OK — return mixed data; the app under test performs filter/empty-state logic; the mock refuses every write the scenario does not declare.
5. Product bugs stay red (`status: bug`).

## Automation

- One test per automated scenario; `scenario_id` label required.
- Do not copy expectations from component implementation; copy from scenario `expected` only. Visual values come from the design reference named in the scenario, never from the app source or from what the running app shows.
- Fail unhandled mock calls with the HTTP method and URL, so an empty accidental response cannot green an empty-state test.

## Text and style (browser runner only)

- Quoted copy: assert the rendered text with `toHaveText(expected, { useInnerText: true })` or `expect(await locator.innerText()).toBe(expected)`, case-sensitive and exact. Also assert `toHaveCSS('text-transform', <value>)`; use `none` when the design shows the copy as typed. Default `toHaveText`, `getByText` and `exact: true` read `textContent` and cannot see `text-transform`.
- Style: for each expected colour, background, font family, font size, font weight and `text-transform`, assert the computed value with `toHaveCSS` or `getComputedStyle` against the scenario's value, per expected visual. `toBeVisible()` alone never satisfies a line.
- Icon: assert the named icon by its identity (icon component name, accessible name or `data-icon` value), never "any svg".
- A unit or jsdom runner reads markup, not what the user sees; it cannot carry a visual line. Bind such scenarios to the browser runner.
- Forbidden: case-insensitive regex, `toContainText`, a regex `toHaveText` or a partial match when the scenario quotes copy.

## Mock write policy

- A mock accepts a write (POST, PUT, PATCH, DELETE) only when the scenario declares it by method, path and body. Any other write fails the test with a message naming the method and URL.
- Parse a request body as JSON only when its content type is `application/json`; refuse a multipart body that has no boundary.
- Route every route the spec registers through the same write policy, including routes added after the mock, so a later overlay cannot serve a write the policy forbids.
- A refusal test asserts the policy's own message. It never passes through `test.fail()`, which turns a wrong failure into a pass.

## Never make a red test green

- No `test.skip`, `test.fixme`, `test.fail`, `test.only`, `test.slow`, `waitForTimeout`, retries or a longer timeout to hide a failure; no inverted assertion; no `--allow-draft-pass` as a finish line.
- No hedged wording in tests or instructions that lets a check pass when its subject is missing.

## Proof

- For each visual value the scenario names, set it deliberately wrong (colour, font, size, case, icon), confirm the test fails on that assertion (not merely because the feature is missing), then restore it. Keep the red output.
- Run the test on the merge base (or with the behaviour deliberately broken) and keep the red output next to the green run.
- `node qa/bin/qa.mjs check-scenarios --source` enforces Playwright/Testing Library `getByText`/`getByLabelText` with `{ exact: true }`, bans case-insensitive text matchers, rejects visibility-only binding, and rejects skipped, fixme, fail-marked, `.only`, slowed, timeout-extended and retried tests.
- Some runners have a framework path that records these visual checks as data (`qaVisual` / `expectedVisual`); see the parent skill. Use it when your framework has it; the assertions above still apply.
