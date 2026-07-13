# Adaptive Model Orchestration

Use this contract when a harness exposes more than one model family, reasoning
effort, agent, or external AI counterpart. The active thread remains the
coordinator and final authority. Routing adds independent evidence and bounded
execution capacity; it never transfers architecture, security, release, or
validation truth.

## Adoption Profiles

Choose and record one profile during framework adoption:

- `single-agent`: no counterpart is required. Use local self-critique and keep
  every quality gate.
- `adaptive`: use a second reasoning family when it is useful for a substantive
  task and the capability, privacy boundary, latency, and cost are acceptable.
- `always-on-two-family`: every substantive task uses the coordinator plus at
  least one independent counterpart family. If the counterpart is unavailable,
  continue locally without lowering gates and report the capability gap.

`always-on-two-family` is an explicit operator choice, not a portable default.
It is appropriate when the operator has authorized the provider and wants
routine cross-family challenge passes.

## Reasoning Gate

Before substantive execution, classify:

- ambiguity and architecture depth;
- security, authorization, data, dependency, migration, and release impact;
- reversibility and blast radius;
- strength of deterministic validation;
- failed hypotheses or checks;
- disagreement between evidence sources or models;
- whether the work contains independent, non-overlapping units.

Use the smallest capable route:

| Tier | Use when | Typical role |
| --- | --- | --- |
| Fast | Mechanical discovery, extraction, classification, log/test triage, or cheap independent checks | Explorer or condenser |
| Standard | Normal planning, implementation critique, debugging, review, and verification | Advisor, bounded executor, or verifier |
| Deep | Architecture, security/data boundaries, ambiguous root cause, irreversible decisions, conflicting evidence, or repeated failure | Senior advisor or final risk reviewer |
| Delegating deep | Deep-tier difficulty plus two or more genuinely independent exploration, critique, or verification units | Parallel read-only audit or partitioned execution |

Do not promote effort merely because a task is long. Promote when failure is
expensive to detect, evidence is weak or contradictory, or the work benefits
from independent decomposition. Strong deterministic validation often makes a
standard tier sufficient.

## Role Matrix

Keep role assignment capability-first. Verify the live model catalog rather
than assuming a model name or effort level exists.

- Coordinator: owns intent, architecture, integration, escalation, and final
  validation truth.
- Fast peer: handles bounded discovery, extraction, summarization, and
  mechanical checks.
- Balanced peer: provides a separate plan/code review, bounded exploration, or
  implementation critique.
- Deep peer: challenges high-risk decisions or unresolved disagreement.
- External family sidecar: supplies cross-family critique, read-only audit, or
  bounded execution under an architected plan.

Every delegated unit needs a compact brief: objective, role, scope,
`do_not_touch`, source evidence, acceptance criteria, exact checks, security and
data invariants, output cap, stop conditions, and fallback. Keep direction
acyclic: a sidecar must not call the coordinator or recursively create another
orchestration layer.

## Verified Example Profile: Codex + OpenCode/GLM

The installable profile in `skillsets/adaptive-model-orchestration/` maps the
generic roles to a verified family combination:

- active Codex model: coordinator;
- OpenCode GLM fast model: discovery and extraction;
- OpenCode GLM quality model at its normal high setting: default independent
  plan, review, debugging, and verification pass;
- OpenCode GLM quality model at its deepest setting: security, architecture,
  data, migration, release, ambiguous debugging, or final high-risk review;
- Codex Luna-like peer: high-throughput bounded checks;
- Codex Terra-like peer: balanced xhigh plan/code review;
- Codex Sol-like peer: hardest single-path judgment or automatic delegation
  when the live catalog exposes those capabilities.

Model names and supported effort labels are examples, not framework truths.
The profile's doctor check must verify executable, authentication, model,
effort, and agent availability before use. Provider-specific trust and private
context sharing require explicit operator authorization.

## Max And Ultra Decision

Treat `xhigh` (or the provider's normal strong tier) as enough when the scope is
bounded, evidence is coherent, changes are reversible, and validation can
decide correctness.

Promote to `max` for the hardest single reasoning path: security or data
invariants, irreversible architecture, conflicting source-of-truth evidence,
two failed hypotheses/checks, or a load-bearing model disagreement.

Promote to `ultra` only when max-level difficulty also contains multiple
independent units that benefit from automatic delegation. Do not use it for a
tightly coupled edit, a single-file task, or a decision that must remain on one
reasoning path. A model without an `ultra` tier may still participate at its
deepest verified setting.

## Integration And Truth

The coordinator must:

1. Re-read changed and load-bearing cited files.
2. Re-run load-bearing checks locally.
3. Resolve disagreement against source evidence and acceptance criteria.
4. Report each lane as used, blocked, skipped, or unavailable.
5. Distinguish passed, failed, blocked, skipped, and not-run validation.

More models are not a substitute for evidence. Stop adding lanes when another
answer will not change the decision or materially reduce risk.
