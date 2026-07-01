# Agent Orchestration

This document defines when and how to use multiple agents or delegated subtasks.

## Harness Relationship

The master agent owns judgment, architecture, ambiguity resolution, escalation, integration, final validation truth, and delivery.

Delegated agents own only the bounded work assigned to them. When a separate AI tool participates as a peer, executor, verifier, or summarizer, use `CROSS_AGENT_COORDINATION.md` for the communication plan and capability gate. Use `HARNESS_STRATEGY.md` for model-tier routing, cache rules, anti-drift rules, and escalation rules.

## When To Delegate

First verify whether delegation is available in the active tool. Use the capability record in `FRAMEWORK_MANIFEST.md`; do not assume a tool supports sub-agents because this framework describes them.

Also verify whether cross-agent counterpart access is available before planning joint work. A second AI tool may be blocked by missing membership, authentication, permissions, rate limits, cost caps, or output-capture limits.

If the live user prompt includes the exact phrase `subagents swarm allowed`,
treat it as explicit authorization and request wording for sub-agents,
parallel delegation, model routing, and cross-agent counterpart routing for the
current prompt or thread. This satisfies tools that require explicit
delegation wording, while preserving capability checks, privacy filtering,
budget/output caps, anti-drift rules, validation, and single-agent fallback.

Delegate when:

- The work has independent questions that can be answered in parallel.
- Implementation slices have disjoint write scopes.
- A side investigation can run while the main path continues.
- Parallel validation can catch risks without blocking immediate progress.
- Non-trivial planning or architecture needs an independent challenge pass to
  test directives, assumptions, hidden confounders, causal overfitting, and
  candidate patterns before execution.
- In Codex, `gpt-5.3-codex-spark` or an equivalent bounded execution tier can
  handle the first safe sidecar for quick or standard work while the master
  keeps architecture, integration, and final validation.

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

Counterpart:

- A separate AI tool or session coordinated through an explicit communication plan.
- May act as peer critic, explorer, worker, verifier, or summarizer.
- Must receive only the context needed for its role.
- Must follow the output cap, stop conditions, and evidence contract.
- Does not override the coordinator's final integration responsibility.

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

Authorization:
<include only for directive/planning/architecture/challenge briefs: "Authorization: the user explicitly authorizes sidecar/counterpart model use for directive and architecture challenges for this run.">

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
- Use a configured local sidecar first for compact no-tool cognition:
  classification, extraction, terse summaries, prompt compression, naming,
  JSON shaping, and first-pass critique over compact evidence.
- When local-sidecar delegation is required, make multiple independent
  no-tool delegations before implementation or final judgment and reconcile
  the outputs against source-of-truth evidence.
- For Codex model routing, default bounded low-risk tool/file execution to
  GPT 5.3 Spark when available. When a Codex model slug is required, use
  `gpt-5.3-codex-spark`. Before using a stronger Codex tier for delegated quick
  or standard work, run a Spark-fit check and record the exception reason if
  Spark is not used.
- Use narrow context for narrow work; do not hand the full repository context to a task that only needs a focused contract.
- Use a separate AI tool when independent critique, parallel evidence gathering, bounded execution, or verification would improve quality or reduce coordinator context.
- Treat directives, journals, memory, cached conclusions, and prior project
  patterns as challengeable evidence. Do not let them override platform safety,
  current explicit user instructions, repo evidence, tests, or runtime facts.
- For uncertain implementation shape, scan sibling projects only under
  configured workspace roots: repo adoption settings, harness-provided
  workspace roots, `AGENT_WORKSPACE_ROOTS`, or explicit user-provided roots. Do
  not hardcode an operator's personal `~/projects` path as framework truth. Use
  metadata-first scans and verify current-repo fit before adopting.
- Do not require cross-agent work when the user or environment does not have the second tool, membership, authentication, or permission needed.
- Keep architecture, security, data-loss, multi-system, and ambiguous decisions on the strongest available reasoning path.
- If delegation is unavailable or blocked by tool policy, keep the task local and still decompose, validate, and review.
- Do not use cached conclusions when source files, source-of-truth docs, prompt policy, or user freshness requirements changed.
- Report blocked or unavailable delegation as a capability gap, not as a skipped requirement failure.

## Concurrency Rules

- Treat agent slots and thread capacity as a finite external runtime budget.
- Do not spawn speculative agents.
- In Codex environments that expose a thread ceiling, prefer
  `max_concurrent_threads_per_session = 16` unless local policy sets a stricter
  limit.
- Close completed, idle, stale, or prior-workflow agents after capturing any
  needed output.
- Open fresh agents for new delegated work instead of reusing stale context.
- Do not keep agents open between unrelated tasks.

## Integration Checklist

After delegated work returns:

- Read changed files or findings.
- Check for scope drift.
- Check for duplicated abstractions.
- Check for conflict with source-of-truth docs.
- Reconcile counterpart disagreements explicitly when they affect architecture, security, data, release, validation, or scope.
- Run or record validation.
- Close the agent if no longer needed.

## Anti-Patterns

- Delegating the immediate blocking task and waiting idly.
- Assigning the same write scope to multiple workers.
- Asking vague questions like "look around".
- Letting delegated output bypass review.
- Keeping idle agents open.
- Claiming delegated validation passed without checking what actually ran.
