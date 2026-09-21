---
name: scope-advisor
description: Check that a plan, delegated brief, or ongoing result covers the complete user request without adding unrelated work. Use for substantial ambiguity, complex handoffs, material scope revisions, suspected instruction drift, or closeout of multi-part work.
---

# Scope Advisor

Advise on fidelity to the user's intended outcome, inside the platform's
instruction hierarchy and the task's existing authorization boundaries.

1. Load `references/SCOPE_DISCIPLINE.md` and apply it as the controlling
   contract for this review.
2. Build the scope record from the original request, accepted revisions,
   outcomes, boundaries, and only context that affects them.
3. Classify planned work as explicitly requested, necessary, or optional.
   Necessary supporting work needs an evidence-based connection to a requested
   outcome and proportionate impact.
4. Ask only a material unresolved ambiguity; continue independent authorized
   work otherwise. A status question is not a new objective.
5. Return the contract's verdict block: verdict, omissions, additions,
   assumptions, question, next action.

Advice is read-only. This skill cannot approve scope expansion, mutate files,
or invoke other agents; the coordinator stays responsible for scope and
completion.

<!-- typed-decisions:begin -->
## Typed decisions here

Don't judge scope as a whole. For each requirement in the scope record, answer
three separate yes/no questions against the record (not the conversation):
`covered?`, `added-unrequested?`, `rests on an assumption only the user can
settle?`. The verdict is then computed:

- any `covered = no` or `added-unrequested = yes` → `revise`
- else any material user-only assumption → `clarification`
- else → `aligned`

Any other verdict is outside the declared space and counts as a failed
check: re-run it. Contract: the `typed-decisions` skill.
<!-- typed-decisions:end -->
