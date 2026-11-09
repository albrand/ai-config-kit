---
name: qa-scenario-design
description: Draft QA scenarios from a ticket only—specific expected lines, polarities, regression; mocks must not pre-answer.
---

# Scenario design

Read: `references/scenario-schema.md`.

## Rules

- Design from the ticket and acceptance criteria only, not from source code.
- Write `expected` as specific user-visible outcomes (one assert per line). Ban vague wording (“any icon”, “truthy”).
- Each criterion: positive, negative, and `regressionCase: true` scenario.
- If steps mention mocks, MSW, or fixtures: set `mockPolicy: mixed-source` and describe mixed input — never pre-filtered mock payloads that match the expected list.
- Run `node qa/bin/qa.mjs check-scenarios` before opening a QA PR.
