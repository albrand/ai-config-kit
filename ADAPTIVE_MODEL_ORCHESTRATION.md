# Adaptive Model Orchestration

Use this contract when a harness exposes more than one model family, reasoning
effort, agent, or external AI counterpart. The active thread remains the
coordinator and final authority. Routing adds independent evidence and bounded
execution capacity; it never transfers architecture, security, release, or
validation truth. Hermes keeps its current working review route until Codex
(model set in Hermes's own config) is verified there.

## Routing Policy

- Bounded and bulk execution goes to the verified Codex route.
- Architecture, security, authentication, data-loss, release, and final-review
  work stays on Claude. Do not send bulk work to Claude.
- Hermes PR reviews use Codex (model set in Hermes's own config) through
  `bb fleet validate`. Keep the current review route working until Codex
  (model set in Hermes's own config) is verified there; the live route change
  belongs in Hermes's own config.

Use the live provider route for the exact provider, model, and reasoning level;
do not hardcode model names. These assignments describe the user's adopted
policy and are not a portable recommendation to add providers or plans.

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

## Model Policy (owner directive 2026-10-08)

Pick the model and reasoning level from the agent's role. In bb, `bb fleet route`
applies this table; pass `--topic`, `--rejections`, `--complexity` and, when the
work began before its first review, `--started-at` so it can.
Elsewhere (Codex, Claude Code, Elyra cards), name the model and reasoning
explicitly when you start an agent. Never leave it to a default: Codex's config
default is the GPT ceiling, and Claude's is Opus.

| Role | Claude | GPT (Codex) |
| --- | --- | --- |
| Orchestrator (the owner's, or one the owner asked for) | `claude-opus-5-5`; reasoning by complexity: medium, high or xhigh | `gpt-6.1-sol` at high |
| PR reviewer, automation | `claude-haiku-5-5` at low | `gpt-6-luna` |
| Child | `claude-sonnet-5-5`, or `claude-haiku-5-5` for light research and bulk work; low | `gpt-6-luna`; low, medium or high by complexity |

- **Claude children and reviewers.** Reasoning goes from low to high if and
  only if the work keeps being sent back: two rejections in a row, counting
  Hermes non-accepts and failed quality gates together. It never goes past
  high. Light work that keeps coming back
  moves from Haiku to Sonnet.
- **GPT children.** They climb one step for each rejection in a row, and one
  step each when this work has been going back and forth for 2 hours, then
  for 6. That time is the work's own, counted from its first rejection since
  its last accept (or its stated start); a new task in an old group starts at
  zero:
  - `gpt-6-luna` low → medium → high → xhigh
  - → `gpt-6.1-sol` high → xhigh, which is the ceiling.
- **Never astra.** No agent work runs on any astra model; Fleet refuses such
  a turn at dispatch, and also refuses an agent's Codex turn whose model it
  cannot determine. The ceiling also excludes `max` and `ultra` (which
  delegates on its own).
- **Re-route before rework.** A running agent keeps its spawn model. When work
  is rejected, start its next attempt on the route the new count gives.
- **Precedence.** This table takes precedence over the Max And Ultra Decision
  below for delegated agents. That section still applies to work the owner
  starts and runs themselves.

## Role Matrix

Keep role assignment capability-first within the routing policy above. Verify
the live provider and model catalog rather than assuming a name or effort level
exists.

- Coordinator: owns intent, architecture, integration, escalation, and final
  validation truth.
- Codex peer: handles bounded and bulk execution, discovery, extraction,
  summarization, and mechanical checks.
- Claude: handles architecture, security, authentication, data-loss, release,
  and final review. It does not take bulk execution work.
- Hermes: provides an independent PR review through Codex (model set in
  Hermes's own config); it does not execute changes and must never receive
  project source. Keep its current working route until Codex (model set in
  Hermes's own config) is verified there.
- OpenCode: legacy and opt-in only; it is not a default route.

Every delegated unit needs a compact brief: the original request as a faithful
excerpt that preserves the relevant requested outcomes, or a reference
demonstrably accessible to the recipient (a fresh-session delegate must actually
be able to read it); the accepted scope revision; the parent outcome; the unit's
bounded responsibility, role, scope, `do_not_touch`, source evidence, acceptance
criteria, exact checks, security and data invariants, output cap, stop
conditions, and fallback. The full original request must remain accessible to
the recipient even when the brief uses a faithful excerpt; if that access
would exceed the recipient's authorized context, keep that work local or
rescope the delegated unit instead of treating the excerpt as sufficient.
`SCOPE_DISCIPLINE.md` owns the scope-record and
handoff contract behind these fields. Keep direction acyclic: a sidecar must
not call the coordinator or recursively create another orchestration layer.

## Installed Codex Skill

The installable skill in `skillsets/adaptive-model-orchestration/` supports
Codex peer selection and the Codex/Claude routing policy. Its doctor checks must
verify the live catalog before use. Do not package or install provider profiles.

A distinct remote-router topology is cmux + Hermes: cmux is the local UI/session
transport and Hermes is the provider router, plan/delegation brain, fallback, and
usage ledger on a Tailscale-only VPS, driven by a local deterministic broker.
It is default-off, one-writer-per-task, and acyclic like the sidecar role above.
See `CMUX_HERMES_ORCHESTRATION.md` and `skillsets/cmux-hermes-orchestration/`;
use `plan-arbiter` for efficient-frontier lane selection across that surface.

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
