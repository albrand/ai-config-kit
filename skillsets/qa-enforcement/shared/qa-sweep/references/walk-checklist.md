# Walk checklist (P1)

Condensed from the dogfood issue taxonomy (Apache-2.0, see LICENSES.md) plus
the meaningful-tests unhappy paths. Work top to bottom at every step; record
every failure as an inventory row, never as a note.

At every page/state:
- console errors and failed requests, not just visible breakage
- empty states, loading states, error states — each must say what happened
  and what to do next; a bare spinner or blank panel is a defect
- clipped/misaligned text, placeholder text left in, wrong labels

At every interactive control:
- invalid input: submit wrong data and READ the error (a rejection that
  cannot be understood is a FAIL)
- missing prerequisite: the state a real workspace is in, not the seed state
- wrong role: each persona that can reach the surface (admin-only checks are
  the most common false pass)
- denied permission: a raw 404/blank/redirect where the product promised an
  explanation is a FAIL
- escape hatches: cancel, back, close, undo, retry, and log out — a modal
  with no exit is a FAIL even when its contents are perfect

Through the whole workflow:
- create/edit/delete cycles end to end, at human pace
- double-submit, refresh mid-flow, and back-button after submit
- the persona reads the outcome: "completed" means the user reached the goal,
  not that a success flag flipped somewhere
- if a later step is blocked, still attempt the remaining steps (back,
  refresh, alternate route) and record each result — the walk continues;
  it does not wrap up early
