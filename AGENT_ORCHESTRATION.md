# Agent Orchestration

This document defines when and how to use multiple agents or delegated subtasks.

## Harness Relationship

The master agent owns judgment, architecture, ambiguity resolution, escalation, integration, final validation truth, and delivery.

Delegated agents own only the bounded work assigned to them. Use `HARNESS_STRATEGY.md` for model-tier routing, cache rules, anti-drift rules, and escalation rules.

## When To Delegate

First verify whether delegation is available in the active tool. Use the capability record in `FRAMEWORK_MANIFEST.md`; do not assume a tool supports sub-agents because this framework describes them.

Delegate when:

- The work has independent questions that can be answered in parallel.
- Implementation slices have disjoint write scopes.
- A side investigation can run while the main path continues.
- Parallel validation can catch risks without blocking immediate progress.

Keep work local when:

- The next step depends on the result immediately.
- The task is small or tightly coupled.
- The subtask requires nuanced judgment that would be expensive to specify.
- Delegation would duplicate work already in progress.

## Agent Roles

Master:

- Owns the full user intent and source-of-truth order.
- Decomposes work into verifiable units.
- Chooses which model or agent tier each unit deserves when routing is available.
- Keeps global context and final review.
- Decides when to escalate or stop.

Explorer:

- Read-only.
- Answers a narrow codebase or evidence question.
- Should return paths, findings, and confidence.
- Should not edit files.

Worker:

- Owns a bounded implementation slice.
- Must have a clear write scope.
- Must avoid reverting unrelated changes.
- Must list changed files and validation.

Verifier:

- Runs focused checks or reviews a risky area.
- Should not duplicate implementation.
- Reports pass, fail, blocked, skipped, and residual risk.

## Delegation Brief Template

Use this structure:

```md
Task:
<specific bounded objective>

Scope:
<files/modules/areas owned by this agent>

Do not touch:
<files/modules/areas outside scope>

Context:
<source-of-truth details needed>

Allowed outputs:
<exact output shape and forbidden output>

Success criteria:
<what must be true when done>

Validation:
<commands, checks, or evidence required>

Escalation conditions:
<when to stop and return control to the master>

Expected output:
<findings, patch summary, changed files, validation>

Coordination:
You are not alone in the codebase. Do not revert or overwrite changes outside your scope. Adapt to nearby changes.
```

## Ownership Rules

- Each worker gets a disjoint write set.
- Explorers can inspect overlapping areas because they do not write.
- The main agent owns integration.
- The main agent reviews delegated output before relying on it.
- The main agent is responsible for final validation truth.
- Delegated agents do not change architecture, add dependencies, expand scope, or modify unrelated files without a new master decision.

## Routing Rules

- Use the smallest model or agent that can complete the task with high confidence and validation.
- Use narrow context for narrow work; do not hand the full repository context to a task that only needs a focused contract.
- Keep architecture, security, data-loss, multi-system, and ambiguous decisions on the strongest available reasoning path.
- If delegation is unavailable or blocked by tool policy, keep the task local and still decompose, validate, and review.
- Do not use cached conclusions when source files, source-of-truth docs, prompt policy, or user freshness requirements changed.
- Report blocked or unavailable delegation as a capability gap, not as a skipped requirement failure.

## Concurrency Rules

- Treat agent slots as finite.
- Reuse agents when context matches.
- Do not spawn speculative agents.
- Close idle agents after their output is integrated.
- Do not keep agents open between unrelated tasks.

## Integration Checklist

After delegated work returns:

- Read changed files or findings.
- Check for scope drift.
- Check for duplicated abstractions.
- Check for conflict with source-of-truth docs.
- Run or record validation.
- Close the agent if no longer needed.

## Anti-Patterns

- Delegating the immediate blocking task and waiting idly.
- Assigning the same write scope to multiple workers.
- Asking vague questions like "look around".
- Letting delegated output bypass review.
- Keeping idle agents open.
- Claiming delegated validation passed without checking what actually ran.
