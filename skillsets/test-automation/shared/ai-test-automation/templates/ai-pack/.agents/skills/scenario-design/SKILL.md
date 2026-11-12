---
name: qa-scenario-design
description: Draft QA scenarios from a ticket only—specific expected lines, polarities, regression; mocks must not pre-answer.
---

# Scenario design

Read: `references/scenario-schema.md`.

## Rules

- Design from the ticket and acceptance criteria only, not from source code.
- Write `expected` as specific user-visible outcomes (one assert per line). Ban vague wording (“any icon”, “truthy”). For each UI element, state exact visible text in the letter case shown, plus colour, background, font family, font size, font weight, and icon identity from the design reference, with the source of each value. Missing design reference is an open question—do not omit visual properties. Never record a value observed in the running app as an expected value.
- Quote copy exactly as the design shows it. State the rendered letter case, and the `text-transform` value, so the test can assert both; write `none` when the copy is shown as typed.
- Every expected line that is visual (quoted copy letter case, colour, background, typography, `text-transform`, named icon) is bound to a real-browser runner. A unit or jsdom runner cannot see what the user sees.
- A ticket that changes copy, colour, typography, an icon or layout always has an automated scenario. Do not mark it manual or not-applicable; a manual scenario for a visual line carries a written procedure with measured colour, typography, icon and exact copy.
- Each criterion: positive, negative, and `regressionCase: true` scenario.
- If steps mention mocks, MSW, or fixtures: set `mockPolicy: mixed-source` and describe mixed input — never pre-filtered mock payloads that match the expected list.
- List every write the scenario expects the app to make (method, path, body). The test mock accepts those writes and refuses all others.
- Run `node qa/bin/qa.mjs check-scenarios` before opening a QA PR.
