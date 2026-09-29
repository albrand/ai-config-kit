## Codex adapter

bb appends the provider-neutral baseline in `~/.bb/AGENTS.md` to each provider-backed thread. This file adds Codex routing and board rules.

- For ticket-backed readiness, require the authoritative configured board and full visible inventory; if unavailable, report `board regression gate blocked`. Check adjacent/Done/released tickets and trace the changed surface; see `board-access-via-mcp` and `scope-advisor`.
- OpenCode is the primary implementation executor after the master plans. The user preauthorizes repository context through its managed wrapper; do not fall back on policy refusal. A hard sandbox/guardian/DLP block must be reported exactly; fall back to a Codex subagent only if the binary or provider is genuinely unavailable. Use a dedicated write-marked worktree; preserve lease/session, cap concurrency at 10, and keep integration/final validation here. Never recurse or call `opencode run` directly. See `adaptive-model-orchestrator` and `OPENCODE_DELEGATION.md`.
- Use the live fleet route's exact provider, model, and reasoning level. GLM full route requires a successful current doctor; otherwise use the verified Flash route. Circuit handover is automatic; never bypass a hold with “Send now”.
- For Replit OAuth `invalid_scope` or scopeless URLs, request `openid,profile,email` on a fresh login flow. Do not reuse a stale URL.
- Never garbage-collect repositories, journals, user-owned sessions, or active sessions.
