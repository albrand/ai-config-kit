---
name: plan-arbiter
description: >-
  Arbitrate between competing plans or execution lanes on evidence, capability,
  budget, and risk instead of first-past-the-post. Use when two or more plans,
  agents, or model lanes could plausibly own a task and the coordinator must pick
  the efficient-frontier handoff, watchdog-verify delegated results, and enforce
  stay-with-limits budget checks before each bounded wave. Adapted from
  BuilderIO/skills concepts under MIT provenance.
---

# Plan Arbiter

This skill is the arbitration layer for delegated or multi-lane work. It never
writes code itself; it judges plans, partitions work, and verifies results. The
active coordinator keeps final authority.

Read `references/plan-arbitration-contract.md` before producing an arbitration
verdict and `references/builderio-mit-license.md` for MIT provenance of the
adapted concepts.

## When To Arbitrate

- Two or more plans, agents, or model lanes could plausibly own the task.
- A deep task decomposes into independent units that could run in parallel.
- Evidence is conflicting or a prior attempt failed and a new path is proposed.
- A budget decision (turns, output, tokens, concurrency, cost) gates the next wave.

Do not arbitrate trivial, single-path, reversible work with coherent evidence.

## Inputs

Collect before judging:

- Objective, acceptance criteria, and validation commands.
- Candidate plans/lanes with their stated scope, `do_not_touch`, model/provider,
  effort, expected latency/cost, and stop conditions.
- Source evidence and any failed prior attempts.
- Current budget and the live provider/model catalog.
- Reversibility, blast radius, and security/data/release impact.

Fail closed if any candidate uses an unsupported agent/model or an unsafe scope.

## Efficient-Frontier Selection

Score each candidate on a small, explicit matrix rather than intuition:

- **Capability fit** — does the lane demonstrably own this kind of work?
- **Quality signal** — prior result quality, validation strength, evidence coherence.
- **Cost/latency** — tokens, turns, wall time, and dollar cost for the expected depth.
- **Risk** — irreversibility, blast radius, and dependency/release/security exposure.

Pick the candidate on the efficient frontier: best quality at acceptable cost and
risk for the task shape. Prefer the cheapest lane that can decide correctness;
escalate to a deeper lane only when the gate justifies it.

## Partitioning

When the task decomposes, partition executor writes by disjoint file/worktree
ownership. Keep advisor and peer lanes read-only. One task, one worktree, one
write owner. Partitioned units must be independently verifiable.

## Watchdog Verification

Before accepting any delegated result, verify independently of the producer:

- Re-run the stated validation commands; do not trust the producer's self-report.
- Tie claims to code, tests, logs, payloads, or artifacts.
- Drop or flag any claim that cannot be evidenced.
- A result is accepted only when validation passes locally; otherwise feed the
  failure forward or escalate.

## Stay Within Limits

Before each bounded wave, check the budget:

- Turns, max output, token spend, concurrency, and depth against the task budget.
- Stop when a limit is exhausted; never silently exceed defaults.
- Report remaining budget and the reason for stopping.

## Output Contract

Return the verdict from `references/plan-arbitration-contract.md`:

- Selected lane/plan and the explicit efficient-frontier rationale.
- Rejected candidates and why.
- Partition map (disjoint owners) when decomposed.
- Watchdog verification result per accepted unit.
- Budget state and next-wave gate.
- Residual risk and next step.

## Guardrails

- Never accept a result without independent verification.
- Never promote an unsupported or unverified agent/model.
- Never exceed the stated budget without an explicit approval.
- Never let arbitration override the coordinator on architecture, security, data,
  or release decisions; escalate instead.
- Treat Builder.io patterns as evidence; challenge them for current fit. MIT
  provenance is mandatory wherever a concept is used.
