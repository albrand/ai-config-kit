---
name: adaptive-model-orchestrator
description: Route substantive coding, planning, architecture, debugging, review, security, and research across the active coordinator, an independent external model family such as OpenCode/GLM, and optional fast, balanced, or deep Codex peers. Use when adaptive multi-model orchestration is adopted or requested, including deciding whether normal strong effort is enough or max/ultra is justified.
---

# Adaptive Model Orchestrator

Keep the active Codex thread as coordinator and final authority. Read
`references/ADAPTIVE_MODEL_ORCHESTRATION.md` before routing and
`references/OPENCODE_DELEGATION.md` before using OpenCode.

At every lane start and end, retry, timeout, cancellation, provider switch,
restart, and closeout, load `agent-spend-guard` and run its cross-provider
ownership/spend audit. This applies equally to Codex, Claude Code, and
ACP/OpenCode. Never infer “no leak” from a clean turn status, a stopped UI
spinner, or a provider's self-reported exit alone.

## BB restart and upgrade survival gate

When coordinating a BB daemon/app restart or upgrade, treat worker
detach/adoption as a hard fork invariant. The coordinator must carry a survivor
packet with the active thread/turn, worker PID/PGID, and provider-registry entry;
the restart must leave that worker alive and the next daemon must adopt the same
worker and turn without replaying output or creating a duplicate turn. Validate
the persisted thread state, worker identity, registry/adoption state, and
exactly-once completion events after the new daemon is ready. A successful
process exit or new daemon PID is not proof. Never stop active agents merely to
make an upgrade pass; if adoption fails, stop the rollout and report the exact
blocker. The first-install registry-format migration is the only documented
exception and requires the no-running-thread gate. Use the fork runbook at
`docs/fork/3143-agents-outlive-daemon.md`, and label real Electron quit/reopen
evidence separately from source-level or unit-test evidence.

## Capability Gate

1. Read current user, repository, privacy, and mutation constraints first.
2. Discover the live executable, provider, model, effort, and agent catalog.
3. Select the adopted profile: `single-agent`, `adaptive`, or
   `always-on-two-family`. Never silently promote a portable install to
   always-on external routing.
4. Record the expected latency/cost, context boundary, output cap, stop
   conditions, and local fallback.
5. Keep offline package validation separate from credentialed runtime probes.

## Route

Classify ambiguity, architecture depth, security/data/dependency/release impact,
reversibility, blast radius, validation strength, failed attempts,
disagreement, and decomposability.

- Fast lane: discovery, extraction, classification, log/test triage, or
  mechanical verification.
- Standard lane: default plan challenge, implementation critique, debugging,
  review, and verification.
- Deep lane: security/data boundaries, irreversible architecture, conflicting
  evidence, ambiguous root cause, repeated failure, or final high-risk review.
- Delegating-deep lane: deep difficulty plus multiple independent units.

Use normal strong effort such as `xhigh` when scope is bounded, evidence is
coherent, changes are reversible, and validation can decide correctness. Use
`max` for the hardest single reasoning path. Use `ultra` only when max-level
difficulty also benefits from automatic delegation across independent units.

For the bundled example profile, run at least one GLM lane for each substantive
task only when the operator adopted `always-on-two-family`. Add Luna-like fast
or Terra-like balanced peers when they own a useful independent lane; add a
Sol-like deep peer only when the reasoning gate justifies it. Model names are
examples—verify the live catalog.

## Brief

Every lane receives: objective, role, exact scope and `do_not_touch`, source
evidence, acceptance criteria, validation commands, security/data invariants,
allowed tools, output cap, stop conditions, and fallback. Keep advisor and peer
work read-only. Partition executor writes by disjoint file ownership.

## Invoke

OpenCode example profile:

```sh
<skill-root>/scripts/run-opencode-sidecar.sh \
  <fast|high|max|audit-high|audit-max|execute-high|execute-max> \
  <workdir> \
  "<bounded brief>" \
  [evidence-file ...]
```

Optional same-provider peer:

```sh
<skill-root>/scripts/run-codex-peer.sh \
  <sol|terra|luna|model-id> \
  <high|xhigh|max|ultra> \
  <workdir> \
  "<bounded read-only critique>"
```

Resolve `<skill-root>` as the installed directory containing this `SKILL.md`.
Both wrappers are examples and fail closed when a capability is missing. Use
environment overrides documented in the scripts rather than editing credentials
or machine paths into the package.

OpenCode calls run through the bundled managed runner. Every run has a bounded
30-minute outer wall-clock deadline by default; callers may set a shorter or
longer explicit deadline with `OPENCODE_RUN_DEADLINE_MS`. Provider request
timeout, stream chunk timeout, agent step ceiling, tool counts, and outer JSON
silence remain distinct signals. To resume the same plan step, set
`OPENCODE_RETAIN_SESSION=1` together
with `OPENCODE_SESSION_ID` (or `OPENCODE_CONTINUE=1`); do not reuse sessions
across unrelated work.

Managed runs inherit `BB_DATA_DIR` and write ownership leases under
`$BB_DATA_DIR/opencode-context/leases`. The lease records the BB thread and
environment IDs plus the child PID. Keep those fields intact: the host daemon
uses them to protect active or restart-adopted threads and to reclaim only old,
orphaned process groups. A run without BB thread ownership is never eligible
for automatic reclamation; use `bb memory status` and `bb memory gc` for the
measured status and bounded cleanup path.

Executor modes additionally require `OPENCODE_ALLOW_WRITES=1` and a marker file
named `.ai-config-kit-sidecar-write-scope` at the workdir root. Create the marker
only in a dedicated isolated worktree whose entire contents are safe for the
sidecar to modify; prompt-level file scopes are not an enforcement boundary.

Never interrupt a healthy run solely because it exceeded an expected read,
tool, validation, elapsed-time, or outer-silence count. Stop only for verified
scope/security/destructive drift, a provider or fatal protocol error, caller
cancellation, or a predeclared wall deadline. After a stop, wait for managed
runner quiescence evidence and confirm the worktree is stable before editing or
reassigning it.

## Integrate

Re-read load-bearing files, rerun important checks locally, and reconcile model
claims against source evidence. Report each lane as used, blocked, skipped, or
unavailable. Never infer a check passed. Stop adding lanes when another answer
cannot change the decision or materially reduce risk.
