# Quality Convergence

Quality convergence is the controlled loop for raising work from "changed" to "meets the target with evidence."

Use it when a task is important enough that one implementation attempt plus one validation pass is not enough.

## When To Use

Use quality convergence for:

- Complex implementation work.
- High-risk refactors.
- Security, data, auth, release, or architecture changes.
- Repeated validation failures.
- Review follow-ups where the first patch is not enough.
- Any task where the user asks for high confidence, durable quality, strong tests, or exhaustive cleanup.

Do not use it for:

- Tiny answers.
- Trivial docs edits.
- Work where the user explicitly asks for a single narrow answer.

## Quality Dimensions

Define quality before iterating.

Default dimensions:

- Requirements alignment.
- Functional correctness.
- Test strength.
- Code quality and maintainability.
- Type safety or static analysis.
- Security and data boundaries.
- Performance and scalability.
- UX or accessibility when applicable.
- Operational readiness when applicable.

For each dimension, state:

- Target.
- Evidence source.
- Blocking threshold.
- Whether the check is required or best effort.

## Convergence Loop

Use this loop:

```text
DEFINE TARGETS -> IMPLEMENT -> MEASURE -> SCORE -> FEEDBACK -> ITERATE -> FINAL REVIEW
```

Each iteration must produce:

- Artifact: code, docs, config, report, or generated output.
- Evidence: command output, test result, review finding, metric, screenshot, payload, log, or direct behavior check.
- Feedback: concrete changes needed for the next iteration.

The next iteration should use the previous feedback directly. Do not restart from vague intent after validation has produced specific evidence.

## Scoring

Use numeric scoring only when it improves clarity.

Suggested scale:

- `0-59`: not acceptable.
- `60-74`: incomplete or risky.
- `75-84`: usable with known gaps.
- `85-94`: strong enough for normal completion.
- `95-100`: high-confidence, low residual risk.

Recommended default target:

- Normal code change: `85`.
- Security, data, auth, release, or high-risk work: `90`.
- Strict user request or critical workflow: `95`.

Scores must be backed by evidence. Do not use a score as a substitute for reporting actual checks.

## Iteration Limits

Every convergence loop needs limits.

Default limits:

- Small focused improvement: 3 iterations.
- Normal implementation: 5 iterations.
- Complex refactor or high-risk fix: 7 iterations.

Stop early when:

- Target quality is met.
- Remaining gaps require a user decision.
- Validation is blocked by environment or credentials.
- The same failure repeats without new evidence.
- Quality plateaus for two consecutive iterations.
- The fix would require expanding scope beyond the user request.

When stopped before target, report the current score, evidence, blocker, and smallest next decision.

## Breakpoints

Use human breakpoints when continuing would commit to a meaningful direction.

Breakpoint examples:

- Architecture or data model choice.
- Security or permission tradeoff.
- Destructive or hard-to-reverse operation.
- Scope expansion.
- Validation failure that contradicts the plan.
- Quality plateau where multiple next paths are plausible.

A breakpoint should include:

- Decision needed.
- Options.
- Evidence.
- Recommendation.
- Consequence of proceeding.

## Evidence Packet

Before completion, produce a compact evidence packet:

- Requested outcome.
- Quality dimensions used.
- Iterations run.
- Checks passed.
- Checks failed.
- Checks blocked, skipped, or not run.
- Remaining gaps.
- Current readiness level.

## Anti-Patterns

- Iterating without changing the approach.
- Raising a score without new evidence.
- Treating a broad green check as proof of the specific outcome.
- Continuing after repeated failure without escalation.
- Hiding blocked validation behind a confident final message.
- Expanding scope silently to make a score look better.
