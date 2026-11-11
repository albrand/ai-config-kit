---
name: qa-scenario-design
description: Draft QA scenarios from a ticket only—specific expected lines, polarities, regression; mocks must not pre-answer.
---

# Scenario design

Read: `references/scenario-schema.md`.

## Rules

- Design from the ticket and acceptance criteria only, not from source code.
- Write `expected` as specific user-visible outcomes (one assert per line). Ban vague wording (“any icon”, “truthy”). For each UI element, state exact visible text in the letter case shown, plus colour, background, font family, font size, font weight, and icon identity from the design reference, with the source of each value. Missing design reference is an open question—do not omit visual properties. Never record a value observed in the running app as an expected value.
- Each criterion: positive, negative, and `regressionCase: true` scenario.
- If steps mention mocks, MSW, or fixtures: set `mockPolicy: mixed-source` and describe mixed input — never pre-filtered mock payloads that match the expected list.
- Run `node qa/bin/qa.mjs check-scenarios` before opening a QA PR.
