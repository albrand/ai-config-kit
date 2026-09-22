---
name: execution-ownership
description: >
  Use before starting expensive, release, migration, or otherwise single-flight
  agent work that must not run concurrently for the same repository, worktree,
  branch, commit, and operation. Acquires a fail-closed host lease with owner
  metadata, heartbeat renewal, deterministic stale handling, and release.
verify: "python3 skillsets/agent-runtime/shared/execution-ownership/tests/execution_ownership_test.py"
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

## Batch validation around the lease

Finish the full scoped edit set before acquiring an expensive lint, build, or
full-pipeline lease. While iterating, use only cheap targeted checks for the
changed path. Acquire each expensive gate once for the final candidate and
record its result. If one fails, fix the complete failure cluster and rerun
only that failed gate, at most once per repair; do not rerun successful gates
or launch duplicates. Stop after a second failure and record the gate as
failed. Record skipped or deferred gates with the reason.
