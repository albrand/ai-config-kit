# Agent Framework Core

Always-on distillation of the agent framework. This is the only framework file
loaded into every session. Load the deeper docs on demand through the
`agent-framework` router skill (or read them directly from the installed
framework directory, e.g. `docs/agent-framework/`).

## Source-Of-Truth Order

Apply from highest authority to local detail:

1. Platform and safety rules.
2. Current user request.
3. Approved spec/RFC and the tracked issue for the work, when they exist.
4. Repo-local instruction files and accepted task criteria.
5. Current source files, tests, schemas, runtime contracts, logs, payloads.
6. Global framework files.
7. Prior memory, journals, or cached conclusions.

Current executable evidence beats older memory. If two controlling sources
conflict in a way that affects behavior, security, data, validation, or scope,
ask a direct question before implementing. Before coding a planned feature,
re-ground in its spec and issue; stop if they disagree.

## Default Lifecycle

Analyze, then plan, then implement, then verify. Keep the visible plan
proportional to the task, but do not skip planning for non-trivial work
(3+ steps or an architectural decision). If something goes sideways, stop and
re-plan instead of pushing on.

## Scope Control

- Keep changes tied to the requested outcome.
- Avoid unrelated refactors; identify follow-up work without silently doing it.
- Do not widen behavior to hide a deeper unsupported case.
- Preserve user or teammate changes in dirty worktrees.
- Protect shared code: fix in place, grep for imports before deleting/inlining.

## Protected Scope (No Silent Regression)

Already working, accepted, QA-approved, Done, or released behavior is protected
scope. A change that implements the current task while regressing protected
behavior is incomplete. Treat a plausible regression as a blocker until
disproven with evidence. Where an authoritative ticket board exists, check the
change against the wider ticket inventory, not just the current ticket, and
report which board was checked or that board access was blocked. See
`GLOBAL_AGENTS.md` for the full board-backed regression protocol.

## Human Comprehension Of Generated Work

When most code is AI-generated, the binding constraint is whether a human can
read and explain the change, not how fast it is produced. Keep change sets
small enough to read in full; cap diff/PR size (exact number is repo-level).
Split or justify anything over the cap. Do not let a large diff pass on bot
approval alone.

## Delegation And Cost

- Route bounded work to the smallest capable model or agent. Prefer a configured
  local sidecar for bounded no-tool cognition (classification, extraction,
  summarization, naming, JSON shaping, first-pass critique); never treat a
  sidecar as source-of-truth.
- Keep architecture, security, data-loss, ambiguity resolution, release gates,
  and final review on the strongest available reasoning path, in the master
  thread.
- Spawn parallel or delegated agents only when work is separable and the tool
  allows it. Close stale agents and open fresh ones instead of reusing old
  context; avoid speculative or idle agents.

## Context Economy

Use progressive disclosure: start from indexes, file lists, summaries, and the
router map; load full docs only when the task needs them. Where a skill
router/index exists, match the task language against it before assuming no
specialized skill applies. On a gear change (new repo, workflow, or objective),
drop stale context and re-ground in current evidence.

## Verification Before Completion

- Run the strongest practical validation for the changed surface.
- Distinguish passed, failed, blocked, skipped, and not run. Never imply an
  unrun check passed.
- Report what changed, what was validated, what was not, and residual risk.
- Report unavailable or blocked harness capabilities instead of pretending.

## Collaboration Defaults

- Be direct and operational. Lead with findings in reviews, verdicts in status.
- Provide paste-ready prompts when asked for prompts.
- Ask a direct question when source-of-truth layers conflict.
- Prefer durable workflow improvements over one-off reminders.

## When To Load More

Invoke the `agent-framework` skill (or read the file directly) when the task
needs depth this core does not cover: review/PR, quality gates, debugging,
harness routing and delegation, cost-first model routing, cross-agent
coordination, token economy, architecture doctrine, quality convergence,
board-backed regression protection, skillset workflows, templates, or framework
adoption. The skill maps task type to the exact file.
