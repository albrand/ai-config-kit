# Read the tickets

The ticket is the specification, and tickets are often badly written. Your job
is to turn each one into a list of checkable acceptance criteria the QA agrees
with, without guessing.

## Getting the ticket

Use whatever board tool the QA's agent has, in this order:

1. An MCP server for the board (Atlassian for Jira, Linear, GitHub for issues,
   Azure DevOps). List its tools and use the read tools only.
2. The board's CLI, if the QA is signed in to it (`gh issue view`, `jira`, `linear`).
3. A file: the QA exports the ticket (Jira "Export XML/Word", Linear "Copy as
   Markdown") or pastes the text. Save it under `qa/requirements/source/` and say
   that comments and links may be missing.

Fetch for each ticket: title, description, acceptance criteria (a field or a
section), status, type, comments, linked and parent tickets, subtasks, and the
names of attachments (designs, screenshots). Read attachments you can open.
Read the comments in order: a later comment often changes the description.

Do not change anything on the board while reading. Posting a question as a
ticket comment is a board change: ask the QA first.

## The requirement record

Write one file per ticket, `qa/requirements/<KEY>.json`:

```json
{
  "key": "PROJ-123",
  "url": "https://board.example/browse/PROJ-123",
  "title": "Order summary shows the delivery address",
  "fetchedAt": "2026-01-15T14:02:00Z",
  "revision": "sha256 of the normalised title, description, criteria and pinned comments",
  "criteria": [
    {
      "id": "AC-1f3a9c2e",
      "text": "The order summary shows the customer's delivery address",
      "source": "explicit",
      "from": "description, 'Acceptance criteria' section"
    }
  ],
  "rules": ["Only for signed-in customers"],
  "links": ["PROJ-100 (parent epic)"]
}
```

- `id` is a hash of the criterion's normalised text, so it stays stable while
  the text stays the same and changes when the criterion changes. That lets a
  scenario detect that its criterion was edited.
- `source` is `explicit` (written as a criterion), `derived` (you inferred it
  from the description; the QA must confirm), or `clarified` (it comes from a
  recorded answer).
- `revision` changes whenever the ticket's meaning changes. A later sync that
  sees a new revision must flag the scenarios that cite changed criteria.

## When the ticket is badly written

| Problem | What you do |
|---|---|
| No acceptance criteria | Derive candidates from the description, one observable outcome each. Mark them `derived` and ask the QA to confirm each one. |
| Criteria are vague ("works well", "is fast", "looks right") | Ask for the measurable version: which screen, which data, what the user sees, what number. |
| Description and comments disagree | Show both with their dates and ask which is current. |
| It is a bug report | The expected result is the criterion. The steps to reproduce are the scenario. Ask for the environment and data if missing. |
| It references a design | Read it if you can. Otherwise ask the QA which parts of the design are in scope. |
| It is an epic or a parent | Work on its child tickets. Ask which ones. |
| It changes something that already exists | Find the existing tests for that behaviour. Ask whether they should change. Never edit an old expectation silently. |

## Read the code, but do not let it decide

When the feature exists, read the screen, route or endpoint that implements it,
so your questions are concrete ("the code hides the button for read-only users;
the ticket does not mention roles — should read-only users see it?"). Code shows
what the app does today. Only the ticket and the QA say what is correct.

## Asking questions

- One question per message, with the evidence (ticket text, comment, screen or
  code behaviour) and your suggested answer, so the QA can reply "yes".
- Ask in priority order: questions that change many scenarios first.
- If the QA does not know, ask who does (Product, the developer on the ticket)
  and mark the criterion `blocked` with the question. Keep going on the others.
- When the answer changes the requirement, offer to post it on the ticket as a
  comment so the board stays the source of truth. Post only with approval.

## Recording the answers

Append each answer to `qa/clarifications/<KEY>.json`:

```json
{
  "key": "PROJ-123",
  "entries": [
    {
      "question": "Should read-only users see the map?",
      "answer": "Yes, read-only users see the address and the map.",
      "answeredBy": "QA's name or board/GitHub handle",
      "answeredAt": "2026-01-15",
      "criteria": ["AC-1f3a9c2e"],
      "postedTo": "board comment id, or null"
    }
  ]
}
```

These files are part of the requirement: the revision hash includes them, and
reviewers see them in the pull request.
