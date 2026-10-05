---
name: codex-delegation
description: Use when routing bounded or bulk execution through the verified Codex route, including choosing the accountable BB thread or fleet path, preparing a bounded brief, and reconciling worker output.
verify: test -f skillsets/agent-runtime/shared/codex-delegation/SKILL.md
verified: 2026-10-05
---

# Codex Delegation

Bounded and bulk execution uses the live verified Codex route. Quality-critical
architecture, security, authentication, data-loss, release, and final-review
work stays on Claude; do not send bulk work to Claude. GLM is retired for
ordinary execution and fallback. Keep Hermes's current review route working
until Codex (model set in Hermes's own config) is verified there; manage the
live route change in Hermes's own config.

1. Resolve the current Codex provider, model, and reasoning level from the live
   route. Do not copy a stale model ID or invoke an untracked subprocess.
2. Use a BB thread or fleet member when the harness offers one, so ownership and
   usage remain attributable. Never call `opencode run` for this route.
3. Give the worker the relevant user request, accepted scope, parent outcome,
   plan, exact owned paths and `do_not_touch` paths, source evidence, acceptance
   criteria, exact checks, security and data invariants, allowed tools, output
   cap, stop conditions, and fallback.
4. Keep one writer per branch and worktree. Executor work uses a dedicated
   isolated worktree with explicit write authorization. Do not recurse into
   another orchestrator or sidecar.
5. Treat worker output as evidence. Re-read changed files, rerun important
   checks, resolve disagreements against source, and keep final integration and
   validation with the coordinator.

For Hermes PR review, use `bb fleet validate` with bounded evidence. After its
replacement is verified, the route uses Codex (model set in Hermes's own
config). Never pass a `--model` override to `acp-hermes-agent`. Never place or
retain project source on Hermes; send only bounded review context via the
approved broker.
