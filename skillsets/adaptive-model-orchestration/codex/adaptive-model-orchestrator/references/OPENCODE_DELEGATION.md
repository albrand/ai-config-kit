# OpenCode Delegation Contract

This is the provider-specific execution contract for using OpenCode as an
external sidecar. Read `ADAPTIVE_MODEL_ORCHESTRATION.md` first. That file owns
the portable routing and effort policy; this file owns the OpenCode handoff.

OpenCode is optional unless an adopted profile explicitly requires it. Never
assume the executable, provider membership, authentication, model, effort
variant, agent name, private-context authorization, or broad filesystem access
exists. Verify those capabilities with a small probe.

## Modes

- Advisor: tool-free critique over a compact evidence packet.
- Explorer: read-only repository discovery and evidence extraction.
- Auditor: deeper read-only inspection when a packet is insufficient.
- Executor: bounded implementation of an already architected plan in a
  disjoint scope.

Direction is acyclic: coordinator -> OpenCode -> result -> coordinator.
OpenCode must not call the coordinator, another orchestrator, or another
sidecar. The coordinator retains architecture, integration, security, release,
and final validation authority.

## Capability And Authorization Gate

Before the first call:

1. Resolve `opencode` from `OPENCODE_BIN` or `PATH` and record its version.
2. Verify the configured provider, model, effort variant, and primary agent with
   a tiny no-tool probe. Agent names and CLI flags may change across versions.
3. Keep package validation offline. Authentication and live model probes belong
   to an explicit runtime doctor check.
4. Confirm whether sending repository context to the configured provider is
   authorized. Sanitize secrets and minimize the evidence packet regardless.
5. Record workdir, allowed tools, mutation boundary, time/output cap, stop
   conditions, and single-agent fallback.
6. For executor mode, use a dedicated isolated worktree whose entire root is
   authorized for modification. The bundled wrapper also requires the explicit
   write environment gate and marker documented by its skillset.
7. If an adopted always-on profile requires OpenCode and it is unavailable,
   report the blocked lane and continue locally without weakening gates.

Do not encode `danger-full-access`, automatic approval, private-context trust,
or unrestricted external directories as portable defaults. Those are local
operator decisions.

## Handoff Packet

Send only what the mode requires:

- `objective` and sidecar role;
- ordered plan for executor mode;
- in-scope paths and `do_not_touch` paths;
- authoritative evidence or attached compressed packet;
- acceptance criteria and exact validation commands;
- security, data, dependency, and release invariants;
- allowed tools and mutation boundary;
- expected artifact/output shape and hard output cap;
- stop conditions and fallback.

For a directive, planning, architecture, or challenge pass, include the
authorization required by the active environment. Do not manufacture
authorization inside a portable template.

## Invocation Pattern

Prefer the wrapper and lean config in
`skillsets/adaptive-model-orchestration/`. A direct invocation has this shape:

```sh
OPENCODE_CONFIG_DIR="<lean-config-dir>" \
  opencode run "<bounded brief>" \
  --format json \
  --auto \
  --pure \
  --dir "<workdir>" \
  -m "<verified-model>" \
  --agent "<verified-agent>" \
  -f "<optional-evidence-file>"
```

Treat `--pure`, `--variant`, `--agent`, and agent names as feature-gated. Probe
the installed version before depending on them. Keep OpenCode's remote session
publication feature disabled (`share: "disabled"`; do not pass `--share`)
unless the user explicitly requests publication.

For advisor calls, prefer precomputed evidence over asking a live repo-bound
agent to rediscover the entire task. For execution, split plans into disjoint
file scopes and attach the plan rather than embedding a large transcript.

## Executor Output

Require:

```yaml
status: done | partial | blocked
plan_progress: <completed steps>
changes:
  - path: <file>
    summary: <one line>
artifacts:
  - <path>
validation:
  - check: <command>
    result: pass | fail | blocked | skipped | not_run
gates_preserved: <quality and security gates, or blocker>
residual_risk: <short>
next_step: <short or null>
```

The coordinator re-reads changes, verifies load-bearing claims, reruns the
important checks, and resolves disagreements. OpenCode output is execution or
advisory evidence, never final release truth.

## Recovery

Retry once only for a clearly transient failure. On timeout, retain partial
structured output and decide whether local evidence is already sufficient.
Return `blocked` rather than expanding scope, choosing new architecture,
adding dependencies, weakening gates, or taking a destructive action not
authorized by the brief.
