---
description: Arbitrate between competing plans or execution lanes on evidence, capability, budget, and risk; pick the efficient-frontier handoff, partition writes by disjoint ownership, watchdog-verify delegated results independently, and enforce stay-with-limits budget checks before each bounded wave. Builder.io concepts under MIT provenance.
argument-hint: [objective] --plans <paths or descriptions>
allowed-tools: Read, Grep, Glob
---

# Plan Arbiter

Judge plans, partition work, and verify results. This command does not write
code; it produces an arbitration verdict. The active coordinator keeps final
authority.

User input:

`$ARGUMENTS`

## Workflow

1. Load `skillsets/cmux-hermes-orchestration/codex/plan-arbiter/references/plan-arbitration-contract.md`
   and the MIT provenance reference before producing a verdict.
2. Create a todo list.
3. Collect inputs: objective, acceptance criteria, validation commands, candidate
   plans/lanes with scope/`do_not_touch`/model/effort/cost/stop conditions,
   evidence, prior failures, current budget, and the live catalog.
4. Fail closed on unsupported agents/models or unsafe scopes.
5. Score each candidate on the efficient-frontier matrix: capability fit, quality
   signal, cost/latency, risk. Pick the best quality at acceptable cost and risk;
   prefer the cheapest lane that can decide correctness.
6. If decomposed, partition executor writes by disjoint file/worktree ownership;
   keep advisor/peer lanes read-only. One task, one worktree, one write owner.
7. Watchdog-verify: re-run validation independently of the producer; tie claims to
   evidence; drop unverified claims; accept only locally-validated results.
8. Check the budget before each wave; stop when a limit is exhausted; report
   remaining budget and the next-wave gate.

## Output

Return the verdict from `plan-arbitration-contract.md`: selected lane and
rationale, rejected candidates, partition map, watchdog verification per unit,
budget state, residual risk, and next step. Record Builder.io MIT provenance
wherever an adapted concept is used.
