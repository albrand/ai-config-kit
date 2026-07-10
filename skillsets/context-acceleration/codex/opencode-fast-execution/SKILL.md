---
name: opencode-fast-execution
description: Build compact GLM 5.2 packets, measure run quality, and garbage-collect completed orchestrator context.
---

# Opencode Fast Execution

Use for bounded opencode/GLM 5.2 delegation, slow-run diagnosis, or context
maintenance.

1. Resolve architecture and security on the master thread.
2. Build a packet containing objective, plan, scope, do_not_touch, inputs,
   quality_gates, security_gates, output, and escalation.
3. Run `scripts/classify-call.mjs` automatically; never ask the user or GLM to
   select execute, advisor, repair, or blocked mode.
4. Invoke execution through `scripts/run-managed.mjs -- opencode run ...` so
   JSON streams normally while completed orchestrator-owned sessions are
   deleted after success. Use `--retain-session` only for same-step continuation.
5. For advisors, use `ADVISOR_PACKET_V1`, `/tmp`, a tool-disabled agent, and a
   500-word cap. `--pure` does not disable native tools.
6. Budgets: 8 pre-edit tools, 2 validation calls, 1200-word execution close-out.

## Feedback loop

Record elapsed time, packet size, token counts, tool calls, status, and repair
reason. Mark slow after 8 pre-edit tools, 2 validation calls, or timeout;
insufficient for failed gates, missing close-out, partial/blocked status, or
unmet acceptance criteria; drift for out-of-scope reads/edits. Issue one small
repair packet, then escalate to GPT rather than replaying a broad prompt.

## Context GC

At every boundary retain only close-out, changed paths, failed gates, residual
risk, and next step. Drop raw logs, duplicate excerpts, stale plans, and
completed-agent transcripts. Run `scripts/context-gc.mjs` to audit the complete
opencode database, live agent process RSS, and stale temp packets. Its `--apply`
mode deletes only old files under the OS temp directory. Never delete active or
user-owned sessions; `run-managed.mjs` may delete only sessions it created and
observed finish successfully.

Revalidate load-bearing changes and report measured latency, tools, tokens,
retained session count, and residual risk.
