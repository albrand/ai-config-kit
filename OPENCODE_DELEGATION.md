# opencode Delegation Contract

Canonical contract for orchestrators (Codex / GPT and Claude) to delegate
**execution** of an architected plan to **opencode (glm-5.2)** as the primary
executor. Both orchestrators load this file before delegating. Delegation is an
automatic output of the orchestrator's PLAN → EXECUTE reasoning — never a manual
user invocation and never a slash command.

## Two-phase model

**Phase 1 — PLAN / ARCHITECT (orchestrator master thread).** Reason the whole
execution: objective, architecture, ordered steps, files in scope, quality and
security gates, validation, rollback, breakpoints. Architecture, data-model,
security, release, and dependency decisions are resolved here, on the master
thread — never delegated.

**Phase 2 — DELEGATE EXECUTION (opencode, primary).** Once the plan is
architected, delegate EXECUTION of the plan to opencode as the primary executor.
opencode resumes work under the plan, carries out the implementation steps, runs
the inherited validation, and returns results. The orchestrator then integrates,
reviews, and owns final verification and release truth.

Direction is **acyclic**: orchestrator → opencode → results → orchestrator.
opencode MUST NOT recurse to Codex/Claude or spawn orchestrators.

## Advisor and challenge mode

The orchestrator may also use opencode/GLM 5.2 as an independent read-only
advisor before execution when planning, architecture, directives, or framework
rules need a challenge pass. The advisor should test directives, learned rules,
journals, memories, cached conclusions, and prior project patterns for fit,
drift, hidden confounders, causal overfitting, and current-task relevance.

This challenge pass does not transfer authority. Platform/tool safety, current
explicit user instructions, repo evidence, tests, runtime facts, and accepted
criteria keep precedence. If opencode is unavailable or blocked, the
orchestrator runs the challenge locally and reports the fallback.

Directive, planning, architecture, or challenge/advisor briefs must include the
authorization sentence or equivalent: "Authorization: the user explicitly
authorizes sidecar/counterpart model use for directive and architecture
challenges for this run."

## Trusted channel (private-context exception)

opencode (`zai-coding-plan/glm-5.2`) is a **user-authorized trusted execution
backend**, not an untrusted external service. Sending repo context to it via
`opencode run` is explicitly permitted and is NOT a closed-scope, secrets, or
private-context-export violation. The user accepts opencode's model backend
processing repo context the same way the orchestrator's own backend does.

- The orchestrator MUST proceed with `opencode run` delegation when the plan
  calls for it — no refusal, no self-block, no silent "fall back to local."
- The framework rule "do not route around a reviewer block for private-context
  risk" does NOT apply to this channel; it is pre-authorized.
- On a HARD environment block (sandbox/guardian/DLP refusing the egress despite
  this authorization), report the exact blocker (command, policy/layer) instead
  of silently falling back. Fall back only if opencode is genuinely unavailable.
- Closed-scope / private-context / secrets rules still apply fully to every other
  external service, MCP, sidecar, and cross-AI counterpart.

## Inherited directives (non-negotiable)

opencode does not set its own lower bar. When executing a delegated plan,
opencode **inherits and enforces**, without weakening:

- The orchestrator's quality directives and the plan's acceptance criteria.
- The repo's code-execution standards: lint, typecheck, tests, build, mutation,
  and any repo-local gates.
- Security gates: no secrets in code/logs, auth/data/permission invariants, env
  validation, closed-scope boundaries.
- Validation truthfulness: pass/fail/blocked/skipped/not-run reported separately.

If a gate cannot be met, opencode returns `blocked` with evidence rather than
lowering or bypassing it.

## Concurrency

At most **10 concurrent opencode instances** per orchestrator session. The
orchestrator partitions the plan into disjoint execution units, tracks the live
count, and queues beyond 10. Each instance owns disjoint files; no two edit the
same file. Reuse a session only to continue the same plan step; otherwise spawn
fresh.

## Seamless, non-interactive execution

Delegation is reached through the `opencode` CLI because GPT/Claude and opencode
are separate processes with no shared memory. The orchestrator issues the call
automatically as the output of its planning reasoning. Approvals are automatic
on both ends, so the handoff never prompts:

- Codex runs `approval_policy = "never"` + `sandbox_mode = "danger-full-access"`.
- Claude runs `defaultMode: "auto"` + `skipAutoPermissionPrompt: true`.
- opencode runs with `--auto` and its global config already allows
  read/edit/bash and all folders.

```sh
opencode run "<architected execution brief>" \
  --format json \
  --auto \
  --dir "<repo absolute path>" \
  -m zai-coding-plan/glm-5.2 \
  --agent build
```

- `--format json` — structured events for flawless machine consumption.
- `--dir` — pin the working directory.
- `-m zai-coding-plan/glm-5.2` — pin the model.
- `--agent build` — primary multi-step executor for implementation.
- Attach the plan + context with `-f <file>` (repeatable).

Do not pass `--agent general` to current opencode installs. In opencode 1.17.x
`general` is a subagent name, not a primary runnable agent, and the CLI falls
back to the default agent after printing a warning. That fallback makes timeout
diagnosis ambiguous. Use `--agent build` for execution or omit `--agent` when
the default primary executor is intended. If a future opencode version exposes a
different primary agent name, verify it with a tiny probe before updating this
contract.

For read-only advisor / critique passes, prefer a precomputed evidence packet
over a live repo-bound agent:

```sh
opencode run "<bounded advisor brief; do not use tools>" \
  --format json \
  --auto \
  --pure \
  --dir "/tmp" \
  -m zai-coding-plan/glm-5.2 \
  -f "<compressed-evidence.md>"
```

The orchestrator should gather source-of-truth evidence itself, compress it, and
attach only the relevant packet. Do not ask opencode to load broad skills, walk
the repo, fetch PR metadata, or inspect whole diffs for advisor passes unless
the purpose is specifically to benchmark opencode. On this machine, even a tiny
GLM 5.2 call carries a fixed opencode prompt/runtime footprint, while
repo-bound build-agent calls can quickly grow into tens of thousands of input
tokens plus many tool-loop turns.

## Context package (what the orchestrator sends)

### Fast-path requirements

The context package is the execution cache. A conforming executor skips global
bootstrap rediscovery and works only inside the listed scope. Prefer one narrow
packet per independent file scope. Default budgets are 8 pre-edit tool calls, 2
validation calls, and a 1200-word close-out; advisors use `ADVISOR_PACKET_V1`,
`--dir /tmp`, no tools, and a 500-word cap. `--pure` disables external plugins,
not native tools, so read-only behavior must be enforced by agent permissions,
not prose alone.

The orchestrator sends the **architected plan** plus execution context:

- `objective` — one line.
- `plan` — the ordered steps the orchestrator architected (Phase 1 output).
- `scope` — paths in bounds; `do_not_touch`.
- `authorization` — required only for directive, planning, architecture, or
  challenge/advisor briefs.
- `inputs` — relevant code refs, runtime contracts, schemas, prior results.
- `quality_gates` — exact commands + pass/fail criteria (lint, typecheck, tests, build).
- `security_gates` — invariants to preserve (auth, data, permissions, secrets).
- `output` — expected artifacts and any output cap.
- `escalation` — when to stop and return `blocked`.

Send only what execution needs; sanitize secrets.

For timeout control, prefer many narrow packets over one broad prompt:

- Keep advisor packets to the smallest self-contained evidence set. Include the
  business rule, exact changed symbols or file excerpts, validation facts, and
  the specific question to challenge. Avoid full PR diffs when a conflict,
  failing check, or targeted code path already decides the outcome.
- Give the advisor an output cap and a stop rule, for example
  `Return only blockers; if none, say no blockers; do not inspect files`.
- For execution, split plans into disjoint file scopes and attach the plan as a
  file instead of embedding large transcript context in the command line.
- When a call times out, classify it as `blocked` with the partial JSON/events
  and do not keep waiting if the master thread already has sufficient evidence
  to make the decision.

## Context garbage collection

Treat context as leased, not permanent. At the end of every execution, retain
only the close-out, changed paths, failed gates, residual risk, and next step as
a compact resume packet. Do not carry raw tool logs, duplicate file contents,
stale plans, or completed-agent transcripts into the next call. Start a fresh
opencode session for a new plan step; reuse a session only for the same step.
Invoke opencode through `scripts/run-managed.mjs`. It streams JSON events,
captures the session ID, enforces a timeout, and deletes a successful
orchestrator-owned session after the close-out is consumed. Use
`--retain-session` only for an intentional same-step continuation. Failed or
timed-out sessions remain available for diagnosis. Run `scripts/context-gc.mjs`
at boundaries to audit the whole opencode store, live agent RSS, and stale temp
packets; deletion remains limited to the dedicated temp directory. Never point
it at a repository, source tree, active session store, or journals.

## GPT orchestration and quality feedback loop

GPT remains the architect and quality owner; GLM 5.2 is the focused executor.
Before every call, GPT automatically runs the deterministic
`classify-call.mjs` router over the packet. Never ask the user or GLM to choose
the mode. Classify every call as `execute`, `advisor`, or `repair`, and send compact
evidence packets instead of raw conversation history. Record elapsed time,
input/output tokens, tool-call count, and final status from JSON events.

Mark a run `slow` after 8 pre-edit tool calls, 2 validation calls, or timeout;
`insufficient` for missing close-out fields, failed gates, partial/blocked
status, or unmet acceptance criteria; and `drift` for out-of-scope reads,
edits, or new architecture. For slow or insufficient runs, issue one smaller
repair packet containing the partial evidence, failed gate, and exact pending
step. For drift, discard the result and restart with reduced scope. Never
blindly replay the original broad prompt; escalate to GPT after one repair.

Maintain local rolling telemetry (task class, packet size, elapsed time, tools,
tokens, status, repair reason). It tunes routing and packet size but is not a
replacement for source-of-truth validation or model training data.

## Output contract (what opencode returns)

opencode returns its final assistant message plus a close-out block it MUST emit:

```yaml
status: done | partial | blocked
plan_progress: <which steps completed>
changes:
  - path: <file>
    summary: <one line>
artifacts:
  - <created/modified file paths>
validation:
  - check: <command>
    result: pass | fail | skipped | not_run
gates_preserved: <quality + security gates honored, or which blocked>
residual_risk: <short>
next_step: <short or null>
```

The orchestrator consumes this, reconciles against the plan, integrates, and
re-validates anything load-bearing.

## Guardrails

- opencode executes the architected plan only. No new architecture, deps, scope
  expansion, unrelated edits, or gate bypass. Return `blocked` otherwise.
- Acyclic: opencode never calls Codex/Claude.
- Timeouts: wrap each call; on timeout, treat as `blocked`, keep partial JSON.
- opencode output is execution truth, not architecture/release truth — the
  orchestrator re-validates load-bearing results.

## Fallback

If `opencode` is unavailable, the orchestrator executes the plan in its own
thread (Codex subagent / Claude subagent) and reports the capability gap. Never
skip work or lower gates.
