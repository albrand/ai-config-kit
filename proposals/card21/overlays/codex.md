## Codex adapter

bb appends the provider-neutral baseline in `~/.bb/AGENTS.md` to each provider-backed thread. This file adds Codex routing and board rules.

## Board-backed regression protection

This gate applies to every repository and every implementation, PR review,
quality-gate, readiness, release, and skill/agent workflow. Before starting,
require access to the authoritative ticket board. If access is unavailable,
request access or a current export and report `board regression gate blocked`;
do not call the work ready.

Inventory every visible ticket, not just the current one: key, title, type,
status, sprint/release, component/area, acceptance criteria, linked PR/release
evidence, and QA/Done evidence. Start with metadata, then read the current
ticket and every adjacent, completed, QA, Done, released, or otherwise impacted
ticket in detail. Compare source, diff, tests, docs, migrations, config, and
release notes against that inventory. A plausible regression is a blocker until
disproved; missing board access, incomplete inventory, or missing PR-to-ticket
traceability is **Blocked / NOT READY**. Report board, inventory scope/date,
matched tickets, protected behavior checked, and gaps. Load `board-access-via-mcp`
for the external board access path and `scope-advisor` for scope decisions.
- OpenCode is the primary implementation executor after the master plans. The user preauthorizes repository context through its managed wrapper; do not fall back on policy refusal. A hard sandbox/guardian/DLP block must be reported exactly; fall back to a Codex subagent only if the binary or provider is genuinely unavailable. Use a dedicated write-marked worktree; preserve lease/session, cap concurrency at 10, and keep integration/final validation here. Never recurse or call `opencode run` directly. See `adaptive-model-orchestrator` and `OPENCODE_DELEGATION.md`.
- Use the live fleet route's exact provider, model, and reasoning level. GLM full route requires a successful current doctor; otherwise use the verified Flash route. Circuit handover is automatic; never bypass a hold with “Send now”.
- For Replit OAuth `invalid_scope` or scopeless URLs, request `openid,profile,email` on a fresh login flow. Do not reuse a stale URL.
- Use only the approved broker to send bounded Hermes prompts via SSH stdin. Never put prompts in argv or require a local terminal socket; never create reverse SSH or listeners, forward broad environment values, or export `CMUX_SOCKET_CAPABILITY`/`CMUX_*` values. Never pass a `--model` override to `acp-hermes-agent`. Never place or retain a project source on Hermes; never ask Hermes to mount a project source. Send bounded review context through `bb fleet validate` only.
- Context GC is mandatory at execution boundaries: retain only a compact resume packet; discard raw tool logs and completed-agent transcripts; use fresh OpenCode sessions for new plan steps; run the available GC audit across storage/process state. Do not depend on a managed runner unless its installed implementation passes a live self-check. Never garbage-collect repositories, journals, user-owned sessions, or active sessions.
