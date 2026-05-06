# Harness Strategy

This document defines how an AI harness should route work across a master agent, delegated agents, model tiers, cache, validation, and escalation.

## Core Principle

Cost optimization is not about using fewer tokens. It is about using the right tokens in the right place with the right model.

The strongest available reasoning should own judgment. Cheaper or narrower execution paths should own bounded work that can be specified and validated.

## Harness Lifecycle

Use this lifecycle for non-trivial work:

```text
CLASSIFY -> PLAN -> DECOMPOSE -> ROUTE -> EXECUTE -> MEASURE -> ITERATE -> REVIEW -> DELIVER
```

The master agent owns the lifecycle. Delegated agents or smaller models may perform slices, but they do not own the global direction.

## Workflow Tracks

Classify substantial work before routing:

- `quick`: clear bug, small feature, narrow docs or config change.
- `standard`: normal implementation with tests and review.
- `big-change`: architecture, security, data, migration, release, or broad refactor.
- `recovery`: failing tests, CI, deployment, environment, or runtime incident.
- `review`: PR, diff, design, or readiness review.

The track controls depth, not ego. A small-looking change can become `big-change` when it touches safety, data, auth, release, or shared architecture.

At the end of each workflow, state the next required step or the smallest useful follow-up. Do not leave the user guessing whether to test, review, deploy, resume, or decide.

## Process Discipline

For repeatable workflows, treat the plan as a process contract:

- Define phases in order.
- Define entry criteria for each phase.
- Define exit criteria and evidence for each phase.
- Define breakpoints where user approval is required.
- Define stop conditions before work begins.
- Do not skip ahead because the next task is convenient.

If a workflow becomes recurring, promote it into a skill, repo instruction, quality gate, or automation.

## Capability Negotiation

Before substantial work, the master agent should record which harness capabilities are actually available in the active tool.

Use `FRAMEWORK_MANIFEST.md` for the capability record. At minimum, check:

- File read access.
- File edit access.
- Shell or command execution.
- Validation execution.
- Sub-agents or delegation.
- Model routing.
- Cache or memory.
- Network or external tools.
- Browser or UI verification.
- Persistent journals.

Capability status must be one of:

- `available`: supported and usable now.
- `limited`: supported with constraints that affect routing.
- `blocked`: normally supported but unavailable in this session.
- `unavailable`: not supported by the tool.
- `unknown`: not yet verified.

Do not design a route around an unverified capability. If a capability is blocked or unavailable, choose the local fallback and report the limitation.

## Master Agent Responsibilities

The master agent should own:

- Full user intent.
- Task decomposition.
- Model and agent routing.
- Global context and source-of-truth order.
- Ambiguity resolution.
- Architecture consistency.
- Escalation decisions.
- Final review and delivery.

The master agent should avoid low-level work when a narrower validated path is available:

- Repetitive file formatting.
- Simple extraction.
- Raw log summarization.
- Boilerplate generation.
- Mechanical validation.
- Localized edits with a clear contract.

If delegation is unavailable, too expensive to specify, or blocked by platform policy, the master keeps the work local and preserves the same lifecycle.

## Routing Principle

Use the smallest model or agent that can complete the task with high confidence and practical validation.

Routing must consider:

- Required reasoning depth.
- Blast radius.
- Security or data-loss risk.
- Ambiguity.
- Context size.
- Validation strength.
- User request for fresh reasoning.
- Cache safety.
- Capability availability.

Do not route only by apparent task size. A small-looking change can need frontier reasoning when it affects security, architecture, data, or multiple systems.

Routing output should state:

- What stays in the master thread.
- What can be delegated or run through a narrower model.
- What validation each routed unit must produce.
- Which capabilities are unavailable and which fallback is being used.

## Model Tiers

### Small Or Local Model

Use for cheap, bounded cognition:

- Intent classification.
- File discovery.
- Simple extraction.
- Log summarization.
- Formatting.
- JSON shaping.
- Schema validation.
- Naming suggestions.
- Boilerplate generation.
- Simple deterministic refactors.
- Detecting whether cache is safe.

### Medium Model

Use for moderate reasoning:

- Localized code changes.
- Component implementation.
- API integration.
- Test generation.
- Documentation drafting.
- Simple architectural tradeoffs.
- Mapping requirements to implementation files.

### Large Or Frontier Model

Use for high-leverage judgment:

- Architecture design.
- Ambiguous debugging.
- Security-sensitive work.
- Data model or migration decisions.
- Complex refactors.
- Multi-system planning.
- Domain-critical decisions.
- Final review before merge.
- Prompt or harness redesign.
- Choosing between conflicting technical paths.

## Delegated Task Contract

Every delegated task should include:

- Role.
- Bounded task.
- Required inputs.
- Allowed outputs.
- Owned files or modules.
- Explicit non-goals.
- Success criteria.
- Required validation.
- Escalation conditions.

Delegated agents should not redesign architecture, introduce dependencies, expand scope, or modify unrelated files unless the master explicitly changes the contract.

## Cache Rules

Cache may be used when all of these are true:

- Input is identical or semantically equivalent.
- Source files and source-of-truth documents did not change.
- Prompt, policy, and harness instructions did not change.
- The task is deterministic.
- The user did not request fresh study.

Bypass cache when the user asks to:

- Study again.
- Rethink.
- Reanalyze.
- Start from scratch.
- Validate again.
- Ignore previous assumptions.
- Use latest or current information.
- Compare again.

Cache is an optimization layer, not a replacement for reasoning. Fresh source-of-truth evidence beats cached conclusions.

## Anti-Drift Rules

Delegated agents must not:

- Change architecture without approval.
- Introduce dependencies without approval.
- Modify unrelated files.
- Rewrite large areas unnecessarily.
- Ignore existing patterns.
- Bypass tests or validation.
- Invent missing requirements.
- Expand scope beyond the task contract.

If ambiguity affects the result, the delegated agent must stop and escalate to the master.

## Escalation Rules

Escalate to the master or strongest available model when:

- Ambiguity affects architecture.
- Tests or validation fail repeatedly.
- Security implications exist.
- Data loss is possible.
- Domain logic is unclear.
- Multiple valid approaches conflict.
- Model or agent confidence is low.
- The task spans many files or systems.
- The task changes the harness, prompts, routing, or validation policy.

## Validation And Review

Every code-producing delegated agent must run or produce validation evidence when feasible.

Validation may include:

- Unit tests.
- Type checks.
- Lint checks.
- Schema validation.
- Expected-output comparison.
- Security or permission checks.
- Reproducer re-runs.

If validation fails, iterate narrowly:

```text
Read failure -> identify cause -> patch -> re-run validation
```

Do not jump to unrelated changes.

## Quality Convergence

Use `QUALITY_CONVERGENCE.md` when one pass is not enough.

The master should define:

- Quality dimensions.
- Target score or pass criteria.
- Maximum iterations.
- Plateau conditions.
- Required evidence.
- Breakpoints.

Each iteration should feed measured results into the next attempt. Stop and escalate when quality does not improve, validation is blocked, or the next path requires a user decision.

Before delivery, the master reviews:

- Correctness.
- Consistency with source-of-truth docs.
- Architecture and maintainability.
- Security and data boundaries.
- Validation truth.
- Cost and routing efficiency.

## Delivery Standard

The final report should include:

- What changed.
- Why it changed.
- How it was validated.
- Which harness capabilities were used, unavailable, or bypassed when relevant.
- What was not validated.
- Remaining risks.
