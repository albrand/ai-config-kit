# P1 full-workflow walk and inventory procedure

## P1 Walk and inventory: `.qa/inventory.jsonl` — no fixing

Walk the whole workflow with the bb `browser_*` tools as the persona would.
Rules:

- **Walk to the end.** No issue-count cap, no early wrap-up. If step 3 is
  broken, you still attempt steps 4 and 5 (a later step may be reachable via
  back/refresh, and its state is evidence).
- **Record every defect, including ones you did not cause.**
  `predates_change: true` is a column, never a dismissal — a user hitting the
  wall does not care which commit built it.
- **Do not fix anything yet.** Fixing during the walk truncates the inventory.
  Append each row the moment you see it; never batch at the end.
- Match evidence to the defect: interactive failures need the step sequence
  and the broken state (snapshot refs); visible-on-load defects need one
  annotated screenshot ref. Verify once that it reproduces before recording.
- **A gate failure caused by another writer is a defect, not a flake.** When
  a gate or walk fails because something else changed the same data during
  it (a CI setup, another agent's walk, a seed job), record an inventory row
  with `"kind": "environment_contamination"` and `"writer"`: the CI run id,
  thread id or job that wrote. The gate refuses such a row without a writer.
  Never re-run the gate blind: find the writer, stop the overlap, then re-run
  and re-walk.
- Check the console alongside the UI, and cover the unhappy paths (see

  references/walk-checklist.md): wrong role, missing prerequisite, invalid
  input, denied permission, and every escape hatch (cancel, back, close,
  undo, retry, log out).

One JSON object per line:

```json
{"id": "R1", "step": "open invite", "symptom": "invite link 404s for expired-domain accounts",
 "evidence": "snap-r1-seq", "predates_change": false, "severity": "high", "status": "open"}
```

`status` is `open` until fixed and verified, then `closed`; or `fail_escalated`
with an `escalation` reference (ticket/user decision) when you are not
authorized to fix it. Zero rows is a valid inventory only if the walk reached
the outcome.
