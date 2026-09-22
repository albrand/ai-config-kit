---
name: execution-ownership
description: >
  Use before starting expensive, release, migration, or otherwise single-flight
  agent work that must not run concurrently for the same repository, worktree,
  branch, commit, and operation. Acquires a fail-closed host lease with owner
  metadata, heartbeat renewal, deterministic stale handling, and release.
verify: "python3 skillsets/agent-runtime/shared/execution-ownership/tests/execution_ownership_test.py && python3 skillsets/agent-runtime/shared/execution-ownership/tests/gate_runner_test.py"
verified: 2026-09-21
---

# Execution ownership

Use the executable lease before launching work that must have one owner on the
host. The target identity is the canonical tuple
`repo/worktree/branch/commit/operation`; the script hashes that tuple into a
stable lease key. A held lease is a stop condition, not permission to continue
in parallel.

The lease is host-local, stdlib-only, and stored under
`$XDG_RUNTIME_DIR/ai-config-kit/execution-ownership` or
`~/.local/state/ai-config-kit/execution-ownership`. Lease and owner files are
0700/0600, protected by an `fcntl` lock, and written atomically. Owner metadata
includes PID and process-group ID (`pgid`) so PID reuse can be treated as
ambiguous. When running under BB, `BB_THREAD_ID` is copied to optional
`owner_thread` metadata; outside BB it is omitted. Malformed state, unsafe
paths, clock ambiguity, and an owner on another host fail closed.

```sh
python3 scripts/execution-ownership.py \
  --repo /absolute/repository \
  --worktree /absolute/worktree \
  --branch fix/example \
  --commit 0123456789abcdef0123456789abcdef01234567 \
  --operation expensive-gate acquire
```

The command always emits one JSON object. `acquire` returns `acquired`,
`reclaimed`, `held`, `stale`, or `error`. Save the returned `owner_id` only in
the owning process's protected state, then pass it to `heartbeat` periodically
and `release` when the operation ends. A `stale` result means the heartbeat is
old but the recorded owner process is still alive; it is never reclaimed. A
stale lease is reclaimed only when its recorded owner process is definitely
gone. Any ambiguity returns `error` and leaves the lease untouched.

Useful commands:

```sh
python3 scripts/execution-ownership.py [target options] heartbeat --owner-id ID
python3 scripts/execution-ownership.py [target options] release --owner-id ID
python3 scripts/execution-ownership.py [target options] inspect
```

The optional `--bb-thread-id ID` argument supplies the same `owner_thread`
metadata explicitly when a caller has the BB identifier but does not export
`BB_THREAD_ID`.

Do not bypass `held`, `stale`, or `error` to start duplicate work. The lease
prevents concurrent ownership on the configured host; it does not replace
workflow-level fencing, remote coordination, or recovery of a crashed task's
partial side effects.

## Durable gate and review accountability

The lease alone is not a completion record: `release` intentionally removes
ephemeral ownership state. Before an expensive gate, create a durable run with
`gate-runner.py start` using the same canonical target. The runner persists
whether that exact gate passed, failed, or timed out. A later `start` returns
`already_passed`, `held`, or `repair_required` and must not spawn the gate on
those outcomes. Pair it with the lease around the actual process.

If a gate already passed before this ledger was installed, use `adopt` with
the existing artifact and measurement to record that fact; do not rerun a
successful gate merely to populate the ledger.

```sh
RUNNER=scripts/gate-runner.py
python3 "$RUNNER" start --repo /absolute/repository \
  --worktree /absolute/worktree --branch fix/example \
  --commit 0123456789abcdef0123456789abcdef01234567 --gate lint
python3 "$RUNNER" checkpoint --run-id RUN_ID --phase edit-complete \
  --command 'git diff --check' --measurement 'exit=0' --artifact /absolute/evidence
python3 "$RUNNER" finish --run-id RUN_ID --status passed --exit-code 0 \
  --command 'lint command' --measurement 'target-state=recorded' --artifact /absolute/evidence
```

`finish` requires a command, a measurement, and an existing regular artifact;
exit code zero alone is never enough. A failed gate may be repaired exactly
once with `repair --repair-ref`, then must stop after a second failure. Reviews
use `review-start` (300 seconds by default, 900 seconds maximum) and
`review-check`; expiry becomes the durable `timed_out` state instead of an
unbounded wait. `status` reports `stale` after 900 seconds without a
checkpoint, and `close` refuses while a gate or review is still running.
All states are JSON, atomic, locked, permission-tight, and fail closed on
malformed or ambiguous paths. These are typed process states, not model
confidence or a self-reported verdict.

## Batch validation around the lease

Finish the full scoped edit set before acquiring an expensive lint, build, or
full-pipeline lease. While iterating, use only cheap targeted checks for the
changed path. Acquire each expensive gate once for the final candidate and
record its result. If one fails, fix the complete failure cluster and rerun
only that failed gate, at most once per repair; do not rerun successful gates
or launch duplicates. Stop after a second failure and record the gate as
failed. Record skipped or deferred gates with the reason.
