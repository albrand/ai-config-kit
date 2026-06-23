# Operating Model

This document defines the complete lifecycle for agent work.

## Instruction Layers

Apply layers from broad to narrow:

1. Platform/tool rules.
2. User-level global instructions.
3. Global skills.
4. Parent directory instructions.
5. Repo-root instructions.
6. Repo-local skills and process docs.
7. Current prompt.

When layers conflict:

- Higher-priority platform rules win.
- Narrower repo rules define local implementation details.
- The current prompt can narrow the task for this turn.
- If the conflict changes behavior, source of truth, security, or scope, ask a direct question.

## Default Execution Lifecycle

1. Intake.

- Restate the objective internally.
- Identify whether the task is code, review, debugging, planning, docs, config, release, or research.
- Classify the workflow track: quick, standard, big-change, recovery, or review.
- Identify required skills.

2. Discovery.

- Locate applicable instruction files.
- Load `FRAMEWORK_MANIFEST.md` and verify the relevant framework files are present.
- Inspect repository state.
- Read task-relevant source-of-truth docs.
- Map impacted surfaces.

3. Planning.

- State objective, scope, non-goals, assumptions, approach, validation, and rollback.
- State phase gates, breakpoints, and stop conditions for high-risk work.
- Decide what stays local and what can be delegated.
- Decide whether cross-agent coordination, model routing, cache, or fresh reasoning applies.
- Keep judgment and escalation ownership in the master thread.

4. Harness routing.

- Record actual harness capabilities as available, limited, blocked, unavailable, or unknown.
- Decompose work into small, verifiable units.
- Route each unit to the smallest capable model or agent.
- Use a configured local sidecar first for compact no-tool cognition.
- If local-sidecar delegation is required, ask multiple bounded no-tool
  sidecar passes and reconcile them before implementation or final judgment.
- In Codex, prefer GPT 5.3 Spark for the first safe bounded tool/file sidecar
  on quick or standard work when model routing is available and validation is
  cheap. When a Codex model slug is required, use `gpt-5.3-codex-spark`. Before
  using a stronger Codex tier for delegated work, run a Spark-fit check and
  record the exception reason if Spark is not used.
- When another AI tool participates, create the communication plan before joint work.
- Pass only the context required for that unit.
- Define success criteria, allowed outputs, validation, and escalation conditions.
- Bypass cache when sources changed or the user requested fresh analysis.
- If a harness capability is unavailable, keep the same lifecycle locally and report the fallback.
- Before using MCPs or external integrations, verify that the integration is
  enabled for the current repo, folder, or workflow. Ask before using
  repo-scoped or conditional integrations with no routing preference.

5. Implementation or analysis.

- Keep changes scoped.
- Follow repo boundaries.
- Preserve existing workflows.
- Ask when sources conflict.

6. Integration.

- Review changes and delegated work.
- Review counterpart output before relying on it.
- Resolve duplicated logic, boundary leaks, and naming drift.
- Keep unrelated existing changes intact.

7. Self-review.

- Compare output to the request.
- Re-check architecture, state flow, data flow, security, tests, and quality.
- Fix safe issues before completion.

8. Validation.

- Run focused checks first.
- Run broader checks when risk or repo rules require them.
- Capture exact outcomes.
- Use quality convergence when validation shows the first pass is not enough.

9. Close-out.

- Report changed surface.
- Report validation.
- Report skipped or blocked checks.
- Report the next required workflow step when there is one.
- Report residual risk.
- Close or update any local session journal if used.

## Gear-Change Reset

When the user changes workflows, switches repositories, pivots incidents, or
starts a new objective, reset the active scope instead of carrying stale
workflow state forward.

Before the pivot, leave a compact resume packet when useful:

- Current phase.
- Last completed step and evidence.
- Pending breakpoint.
- Blocked or skipped validation.
- Next exact step.
- Residual risk.

Treat context-window overload warnings as a process signal. Compress active
state into a small note or journal entry, discard stale assumptions, and resume
from current source-of-truth evidence.

## Task Classification

Use the task type to choose depth:

- Tiny answer: direct response, no repo scan unless needed.
- Focused code change: inspect affected surface, plan, edit, focused validation.
- Bug: reproduce, diagnose, patch, regression test, validate.
- Big change: architecture plan before edits, slices, rollback.
- Review: findings first, severity ordered, file references.
- PR preparation: real diff, real validation, deployment and rollback notes.
- Docs/config: verify syntax, references, and closed-scope boundaries.

## Source-Of-Truth Rules

Agents should prefer current, local, executable truth over memory:

- Current prompt.
- Current files.
- Current tests and command outputs.
- Current schemas and runtime contracts.
- Current issue or design docs.
- Current logs or payloads.

Memory and prior notes are useful for orientation, but should not override current evidence.

## Scope Control

Agents should:

- Keep changes tied to the requested outcome.
- Avoid unrelated refactors.
- Identify follow-up work without silently implementing it.
- Avoid widening behavior to hide a deeper unsupported case.
- Preserve user or teammate changes in dirty worktrees.

## Reporting Standard

Use concise reports, but include evidence:

- What changed.
- Why it changed.
- What was validated.
- Which harness capabilities were used or unavailable when relevant.
- What was not validated.
- What remains risky.

Never report a repo as green when checks failed, were blocked, or were not run.
