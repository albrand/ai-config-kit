---
name: adaptive-model-orchestrator
description: Route bounded and bulk work to Codex, keep architecture, security, authentication, data-loss, release, and final-review work on Claude, and run Hermes PR reviews through Codex (model set in Hermes's own config). Use when selecting a model lane, coordinating a bounded delegate, or deciding effort and escalation.
---

# Adaptive Model Orchestrator

Follow the adopted routing policy in
`references/ADAPTIVE_MODEL_ORCHESTRATION.md`. Keep the active thread as
coordinator and final authority. GLM is retired for ordinary execution and
fallback. Keep Hermes's current review route working until Codex (model set in
Hermes's own config) is verified there; manage the live route change in
Hermes's own config.

## Capability Gate

1. Read the current request, repository rules, privacy limits, and mutation
   boundary.
2. Query the live route and model catalog. Use the route's exact provider,
   model, and reasoning level; never infer a model name from stale setup notes.
3. Send bounded and bulk execution to Codex. Keep architecture, security,
   authentication, data-loss, release, and final-review work on Claude. Do not
   send bulk work to Claude.
4. Run Hermes PR review through `bb fleet validate` using Codex (model set in
   Hermes's own config) once that replacement is verified there. Until then,
   preserve Hermes's current working review route. Hermes reviews; it does not
   execute changes.
5. Do not pass a `--model` override to `acp-hermes-agent`. Never place or retain
   project source on Hermes; pass only bounded review context through the
   approved broker.
6. Record the role, allowed tools, worktree, mutation boundary, output cap, stop
   conditions, and single-agent fallback before a handoff.

## Choose Effort

- Use the smallest verified Codex peer for bounded discovery, extraction,
  classification, mechanical checks, and bulk execution.
- Use Claude for the quality-critical work listed above. Raise reasoning effort
  when failure is expensive to detect, evidence conflicts, or the work crosses
  security or data boundaries.
- Do not raise effort solely because a task is long. Strong deterministic
  validation may make a lower tier sufficient.
- Do not use OpenCode as a default or alternate GLM route. Its legacy safety
  boundary is in `references/OPENCODE_DELEGATION.md`.

## Brief

Every delegated unit receives the relevant request and accepted scope, exact
responsibility and `do_not_touch` paths, source evidence, acceptance criteria,
validation commands, security and data invariants, allowed tools, output cap,
stop conditions, and fallback. Keep decision work typed and require evidence.
Partition writes by disjoint path ownership. Keep direction acyclic.

## BB Restart And Upgrade Survival

When coordinating a BB daemon/app restart or upgrade, treat worker
detach/adoption as a hard fork invariant. Carry a survivor packet with the
active thread/turn, worker PID/PGID, and provider-registry entry. Validate the
persisted thread state, worker identity, registry/adoption state, and exactly-once
completion events after the new daemon is ready. Never stop active agents to
make an upgrade pass. If adoption fails, stop the rollout and report the exact
blocker. Follow `docs/fork/3143-agents-outlive-daemon.md` and distinguish a real
Electron quit/reopen from source-level or unit-test evidence.

## Integrate

1. Re-read changed and cited source files.
2. Re-run important checks locally.
3. Resolve claims against source evidence and acceptance criteria.
4. Report each route as used, blocked, skipped, or unavailable.
5. Distinguish passed, failed, blocked, skipped, and not-run validation.

More models are not a substitute for evidence. Stop when another answer cannot
change the decision or materially reduce risk.
