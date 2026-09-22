---
description: Arbitrate between competing plans or execution lanes on evidence, capability, budget, and risk; pick the efficient-frontier handoff, partition writes by disjoint ownership, watchdog-verify delegated results independently, and enforce stay-with-limits budget checks before each bounded wave. Builder.io concepts under MIT provenance.
argument-hint: [objective] --plans <paths or descriptions>
allowed-tools: Bash(git:*), Bash(rg:*), Read
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

<!-- typed-decisions:begin -->
## Typed decisions here

The lane is pick-one from the declared candidates, never a lane invented
mid-decision. Score each candidate on separate yes/no questions: capability
verified? within budget? disjoint write ownership? a verification path that
doesn't rely on the lane's own report? Selection is computed from those
answers. A tie or an unknown escalates to the coordinator or the user; it
never falls to a default lane.

Put each yes/no, and the final pick (`--pick` over the declared lanes with
one-line descriptions), to Jev (`typed-decisions` section 10) as an isolated second judge. A
disagreement with your own selection escalates. Contract: the `typed-decisions` skill.

Record it in the decision ledger (`--point route`), with a `--ref` a later agent can find, and resolve it when the truth arrives.
<!-- typed-decisions:end -->
