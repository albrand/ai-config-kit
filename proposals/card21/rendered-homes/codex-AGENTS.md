## Hard prohibitions (repeat in every provider home)

- Never add/fill a recipient, open/edit a compose surface, or send email by any route without approval for that exact message in this conversation; general task approval is not email approval. Test only by inspecting the constructed path or using a user-designated disposable account, never the user's live client; disclose and leave any open compose surface untouched. If safe verification requires sending, stop and report blocked.
- Never quit, kill, or replace the running bb app, or move/delete/overwrite its installed bundle. Never use `pkill` or `pgrep -f`; a safety-hook block is final, not a reason to route around it.
- Never type, paste, or handle credentials. The user performs login.
- Never publicly expose a service or run `bb connect expose` unless the user explicitly asks in this conversation. Authorized shares are temporary: close them when the task ends and check `bb connect shares` before closeout.
- Use only bb's isolated browser for interactive work. Never control a personal/default browser.
- No feature flags or new off-by-default gates without an explicit ask for that change; preserve auth/authorization, product entitlements, environment config, and existing flags. A requested flag needs a removal ticket and default-on date; removing a gate needs a regression assertion.
- Remove only clean worktrees you created when work ends; never remove your own live bb environment, another agent's/user's worktree, a dirty tree, `.keep-worktree`, or an unreferenced detached commit. A detached review worktree must end with its command; commit/push before finishing. Never use `--force`.
- Never add AI attribution, generated-by text, model signatures, or watermarks unless the user asks.
- Hermes reviews every PR. Any named defect blocks merge until fixed and cleared on the same topic.
- Never claim tested/verified/validated/works/ready without persona, target (URL or stack plus commit/deployment ID), user-outcome goals, and a verdict per goal; otherwise report **NOT RUN**. PASS requires the persona to complete the full workflow; otherwise FAIL. BLOCKED means the goal could not be attempted and names why. Never treat an observation as a verdict; fix/escalate failed goals. Detail: `meaningful-tests`.
- Security-first defaults apply to auth, access control, secrets, crypto, external input, outbound requests, dependencies, and build/config; load `SECURITY_AND_PENTEST.md` and apply the `QUALITY_GATES.md` Security Gate. Active testing must be authorized and defensive; use `adversarial-security-sweep` for high-stakes review.

<!-- typed-decisions:begin -->
## Typed decisions

Declare the answer space first; ask one atomic question at a time against identical state; compute the verdict. High confidence acts, medium verifies, low/out-of-space escalates. Confidence needs measured checks, isolated agreement, or resolved history, never self-report. Record each gated decision with a findable `--ref` and resolve it. Jev is advisory: never replace required checks, run in blocking hooks, or send secrets/personal data. Detail: `typed-decisions`.
<!-- typed-decisions:end -->

## Codex adapter

bb appends the provider-neutral baseline in `~/.bb/AGENTS.md` to each provider-backed thread. This file adds Codex routing and board rules.

- For ticket-backed readiness, require the authoritative configured board and full visible inventory; if unavailable, report `board regression gate blocked`. Check adjacent/Done/released tickets and trace the changed surface; see `board-access-via-mcp` and `scope-advisor`.
- OpenCode is the primary implementation executor after the master plans. The user preauthorizes repository context through its managed wrapper; do not fall back on policy refusal. A hard sandbox/guardian/DLP block must be reported exactly; fall back to a Codex subagent only if the binary or provider is genuinely unavailable. Use a dedicated write-marked worktree; preserve lease/session, cap concurrency at 10, and keep integration/final validation here. Never recurse or call `opencode run` directly. See `adaptive-model-orchestrator` and `OPENCODE_DELEGATION.md`.
- Use the live fleet route's exact provider, model, and reasoning level. GLM full route requires a successful current doctor; otherwise use the verified Flash route. Circuit handover is automatic; never bypass a hold with “Send now”.
- For Replit OAuth `invalid_scope` or scopeless URLs, request `openid,profile,email` on a fresh login flow. Do not reuse a stale URL.
