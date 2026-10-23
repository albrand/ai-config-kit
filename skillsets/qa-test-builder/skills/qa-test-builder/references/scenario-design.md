# Design the scenarios

A scenario is one observable behaviour, written so the QA can judge it without
reading code, and precise enough to automate.

## The scenario file

One file per ticket, `qa/scenarios/<KEY>.json`:

```json
{
  "key": "PROJ-123",
  "requirementRevision": "the requirement record's revision this design was made against",
  "scenarios": [
    {
      "id": "QAS-7K2M9P",
      "title": "Vendor dialog shows the street address with a map below it",
      "criteria": ["AC-1f3a9c2e"],
      "basis": "explicit",
      "layer": "ui-mocked",
      "scope": ["feature", "regression"],
      "preconditions": ["Work order WO-801 is assigned to vendor Harbor Plumbing"],
      "steps": ["Open the work orders board", "Open WO-801's vendor dialog"],
      "expected": [
        "The dialog shows '500 Pine St, St. Louis, MO 63101'",
        "A map of that address is shown below it"
      ],
      "data": "synthetic vendor and work order, defined in the test",
      "binding": {
        "status": "unbound",
        "file": null,
        "awaiting": null
      },
      "approvedBy": null
    }
  ],
  "decisions": [
    {
      "criteria": ["AC-77b0d1aa"],
      "kind": "manual-only",
      "reason": "Needs a real SMS to a phone"
    }
  ]
}
```

### Fields

- `id`: `QAS-` plus six random uppercase letters and digits. Never reuse an ID
  for a different case. When you revise a scenario, keep its ID.
- `criteria`: the criteria this scenario proves. Every criterion needs a
  scenario or a decision.
- `basis`: `explicit` (the criterion says it), `clarified` (a recorded answer
  says it), or `assumption` (you inferred it; this needs a QA answer before
  the scenario can be bound).
- `layer`, the cheapest that proves the behaviour:
  - `api`: an HTTP call to the backend and its response. For rules,
    validation, permissions and persistence.
  - `ui-mocked`: the real UI in a browser with the backend answered by the
    test. For what the screen shows and does. It never proves the backend.
  - `ui-e2e`: the real UI against a real running backend. For journeys where
    the integration itself is the point. Slower and needs an environment, so
    keep these few.
- `scope`: `feature` (this ticket's acceptance; runs on pull requests that name
  the ticket), `regression` (keeps running after the ticket closes), `smoke`
  (release-critical, runs on every pull request).
- `expected`: each line is something the test asserts. If a line cannot be
  asserted at this layer, split the scenario or change the layer.
- `binding.status`: `unbound` (designed, no test), `awaiting-implementation`
  (test written, feature not built; `awaiting` names the branch or pull request),
  `draft` (test written and passing, not yet QA-approved), `ready` (QA-approved).
- `approvedBy`: the QA's GitHub login. CI checks it against the pull request
  author or approving reviewer and the QA team (`qa-authorship.md`); the file
  value alone proves nothing.

### Decisions

When a criterion gets no automated scenario, record why:

- `manual-only`: needs a human or a real external system. Say which.
- `not-applicable`: nothing to verify (copy change, refactor, an epic). Say why.
- `covered-by`: another ticket's scenarios prove it. Name the ticket.
- `other-repository`: the behaviour belongs to another repository's tests (a UI
  criterion in a backend repository). Name the repository.
- `awaiting-implementation`: the feature is not on the main branch yet. Name
  the branch or pull request.
- `blocked`: an open question stops it. Copy the question.

## Rules

1. Behaviour, not implementation. "The dialog shows the address", not "the
   component renders the `address` prop".
2. At least one negative or boundary case for every rule that rejects input or
   restricts access: the empty value, the limit, one past the limit, the wrong
   role.
3. One scenario, one behaviour. A long journey with ten checks becomes several
   scenarios unless the journey itself is the requirement.
4. Do not resolve conflicts. When two sources disagree, ask (`ticket-reading.md`).
5. Name concrete data in preconditions and expected results, so a reader can
   tell what the test proves.
6. In a backend repository, design `api` scenarios only, and record UI-only
   criteria as `other-repository`. In a frontend repository, prefer
   `ui-mocked`, and use `ui-e2e` only when a real backend is available in CI.

## Confirming with the QA

Show the design as a table, one row per scenario, plus one row per decision:

| Scenario | Criterion | Layer | What it checks |
|---|---|---|---|
| QAS-7K2M9P | AC-1f3a9c2e "shows the address" | ui-mocked | WO-801's dialog shows "500 Pine St..." with a map below |
| — | AC-77b0d1aa "sends an SMS" | manual-only | needs a real phone |

Ask: "Is this the right set of checks for this ticket? Anything missing or
wrong?" Change it until they say yes. Then write the scenario files and record
the QA's confirmation (their handle and the date) in the pull request
description.
