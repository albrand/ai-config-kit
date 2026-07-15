# Plan Arbitration Output Contract

Every plan-arbiter verdict must follow this shape. Keep it terse and evidence-backed.

## Verdict

- **selected**: the chosen lane/plan identifier.
- **rationale**: the explicit efficient-frontier reason (capability fit, quality
  signal, cost/latency, risk) — one to three sentences tied to the score matrix.
- **rejected**: each non-selected candidate with a one-line reason.
- **unsupported**: any candidate rejected for unsupported agent/model or unsafe
  scope (fail closed).

## Partition Map (when decomposed)

- One row per unit: owner, disjoint file/worktree scope, validation command, and
  acceptance criteria.
- Advisor and peer lanes marked read-only.
- One task, one worktree, one write owner.

## Watchdog Verification

- Per accepted unit: validation command run locally, result (pass/fail/blocked),
  and the evidence it was tied to.
- Any unverified claim explicitly marked; never report it as accepted.

## Budget State

- Turns, max output, token spend, concurrency, and depth consumed vs. budget.
- Next-wave gate: the condition that must hold to proceed.
- Stop reason if a limit was reached.

## Residual Risk And Next Step

- Residual risk after arbitration and verification.
- The single next step the coordinator should take.

## Provenance

Record Builder.io MIT provenance wherever an adapted concept (plan arbitration,
efficient frontier, agent watchdog, stay within limits) is applied.
