---
name: opencode-fast-execution
description: Build compact GLM execution packets, classify liveness without read-count false positives, manage resumable OpenCode runs, and garbage-collect only safe temporary context.
---

# OpenCode Fast Execution

Use this skill for bounded OpenCode/GLM delegation, premature-stop diagnosis,
run telemetry, or context maintenance. Architecture, security, auth, data-loss,
release strategy, and final validation remain on the coordinator thread.
Install it together with its `adaptive-model-orchestrator` companion; the
managed-runner shim intentionally resolves that sibling package.

## Execute

1. Build a compact packet containing objective, ordered plan, exact scope,
   `do_not_touch`, inputs, quality and security gates, output contract,
   escalation, and stop conditions.
2. Run `scripts/classify-call.mjs`. The coordinator selects the lane; GLM does
   not choose its own role or scope.
3. Invoke OpenCode through `scripts/run-managed.mjs`. It delegates to the
   source-backed managed runner installed with `adaptive-model-orchestrator`.
4. Reuse a session only for the same plan step and retain it explicitly.
5. Revalidate every load-bearing change locally.

Shape executor work as bounded, tool-backed cycles: inspect a focused slice,
edit it, and validate it before expanding. This reduces genuine provider-request
timeouts without converting elapsed time or read counts into interruption
authority.

## Liveness Policy

Tool calls, pre-edit reads, validation calls, elapsed wall time, and outer JSON
silence are telemetry. They are never interruption authority by themselves.
Run `scripts/classify-run-progress.mjs` when a run appears slow.

Continue a live run unless there is evidence of one of these hard stops:

- a verified scope, security, or destructive-action violation;
- a provider or fatal protocol error;
- a caller cancellation signal; or
- an explicit, opt-in wall deadline that was set before the run.

OpenCode provider `timeout`, streamed `chunkTimeout`, and agent `steps` are
different controls; do not reinterpret any of them as a coordinator wall-clock
or read-count budget. The managed runner has no default wall deadline.

After a completed insufficient result, issue at most one compact repair for the
same step. A still-running process is not an insufficient result. After the one
repair, escalate to the coordinator instead of replaying the broad prompt.

## Process Ownership

On cancellation, the managed runner signals the whole owned process group,
waits for closure, performs a bounded kill escalation if required, and reports
the exact stop reason plus process-quiescence evidence. Do not edit or reassign
the worktree until the runner reports the process tree absent and the
coordinator confirms the worktree is stable.

Only newly created, root, coordinator-owned sessions with validated successful
output are eligible for deletion. Interrupted, timed-out, continued, partial,
blocked, failed, or ambiguous sessions are retained.

## Context GC

At execution boundaries retain the close-out, changed paths, failed gates,
residual risk, next step, and measured telemetry. Drop raw logs, duplicate
excerpts, stale plans, and completed-agent transcripts. `scripts/context-gc.mjs`
may delete only old files under the OS temporary directory; it never deletes
repositories or OpenCode sessions.
