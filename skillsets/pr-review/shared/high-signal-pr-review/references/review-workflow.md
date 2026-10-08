# PR review workflow details


1. Read and obey `pr-review-output-contract.md` before any PR review, merge-readiness comment, posted review, or PR body. This is mandatory. If running inside a repo that vendors `agent-config-kit`, also read `skillsets/pr-review/pr-review-output-contract.md`, `REVIEW_AND_PR_FRAMEWORK.md`, `QUALITY_GATES.md`, and `ARCHITECTURE_AND_CODE_QUALITY.md`.
2. Preflight the PR or diff:
   - Confirm it is open and reviewable.
   - Stop or ask before continuing if it is closed, draft, obviously automated or trivial, or already reviewed by the **same authenticated reviewer at the same head**. Reviewer identity and head SHA must match exactly before reusing a prior review; a different reviewer or a different head does not count as already-reviewed.
   - Still review AI-generated PRs when the user asks for it.
   - For queue sweeps, enumerate live open PRs plus any review-required PRs and PRs whose latest non-bot comment or review-thread reply is not from the active reviewer. Treat an author reply or any head change after a review or change-request thread as a trigger to re-review the current head instead of reusing stale blocker text. Deduplicate by PR number, skip closed PRs, and record draft or access-blocked PRs instead of silently dropping them.
   - When the user has authorized merge-after-approval, merge PRs that are already approved or that this review approves only after live mergeability, required checks, unresolved conversations, branch currency, and reviewer identity constraints are verified. Do not merge self-authored PRs, draft PRs, blocked PRs, PRs with unresolved high-signal findings, or PRs whose approval/merge state cannot be verified.
   - When the user delegates review or approval on their behalf as a tech lead, treat that delegation as the active authority for the technical verdict. Do not request product-owner, CODEOWNERS-team, architecture-committee, or similar additional approval. If a current explicit repository rule or ticket names another approval, record it separately as governance or merge metadata; do not use it to avoid or replace the requested technical verdict.
   - Keep governance ownership separate from technical correctness. Review code, tickets, repository docs, tests, and contracts; do not replace a technical approve/request-changes decision with a request for a higher approval level.
3. If the task involves existing PR comments, fetch live top-level comments, reviews, review comments, review threads, head SHA, review decision, and current checks before editing or replying. Map each comment to fixed, evidence-backed reply, not applicable, or still blocked.
4. Resolve instruction scope:
   - Root instructions.
   - Path-scoped `AGENTS.md`, `CLAUDE.md`, Cursor rules, repo docs, or local review rules that cover changed files.
   - PR template and contribution docs when relevant.
5. Reconstruct business intent before judging implementation:
   - Read PR title, body, linked issue, changed-file list, and author-stated tradeoffs.
   - Extract the business rules the PR is trying to satisfy: user workflow, role/permission rules, data lifecycle, external contracts, acceptance criteria, non-goals, and previously working behavior that must remain intact.
   - Build a small review matrix: `business rule / source / changed code / expected behavior / validation evidence`. Use ticket fields, product docs, domain docs, screenshots, API contracts, backend controllers/DTOs, tests, and existing behavior as sources.
   - If the business rule or acceptance criteria are unclear and the uncertainty changes the review verdict, ask one targeted question or mark the PR **NEEDS DISCUSSION**. Do not substitute generic engineering preference for missing business intent.
   - Trace collateral behavior in the affected screen, including loading, empty, error, retry, transition, stale-data, and mutation-failure states. When behavior crosses repository boundaries, inspect the related frontend/backend PRs, DTOs, routes, schemas, and tests before judging the contract.
6. Apply **proportional** board-backed regression checking. Board access is
   mandatory only when a board is configured or linked for the repository, or
   when risk/product/release scope makes board-backed invariants material.
   - Current user and repository instructions govern the applicable board, acceptance criteria, and release requirements. Preserve those requirements without inventing a board prerequisite for unrelated local work.
   - Treat the board as evidence for ticket intent and protected behavior, not as an extra approval hierarchy. A delegated tech-lead review must not solicit separate product-owner or CODEOWNERS sign-off; record any explicit branch/release requirement separately from the technical verdict.
   - When a board applies, inventory the linked and potentially affected tickets: key, title, type, status, sprint/release, component/area,
     acceptance criteria, linked PR/release evidence, and QA/Done evidence when
     present.
   - Check the delta against current, adjacent, QA, Done, released, and
     previously working tickets that share files, routes, contracts, data,
     permissions, or user workflows with the PR.
   - Treat plausible regression of protected board-backed behavior as a Blocker
     until disproven with code evidence and targeted validation.
   - Keep **code findings distinct from board readiness**: report concrete code,
     contract, security, and data findings even when board access is missing. A
     missing or incomplete board blocks only a technical conclusion whose
     acceptance criteria or protected behavior cannot be established from the
     ticket text, repository docs, linked PRs, tests, or other current evidence.
     It does not automatically block delegated technical approval. Do not let board inventory expand re-review blocking scope
     without a causal delta path (see the delta-first re-review contract).
   - When no board is configured or linked, state that and rely on code,
     contract, and runtime evidence instead of blocking on a board that was never
     in scope.
7. Decide whether independent review passes are useful and available. If the platform permits sub-agents and runtime policy allows it, use bounded passes for instruction adherence, business-rule coverage, bug/security/logic, validation/test coverage, architecture, and board-regression mapping. The master thread filters and owns the final verdict.
   Challenge prior review comments, directives, journals, memories, cached
   conclusions, and project patterns as evidence, not authority. For
   architecture or readiness judgments, use an independent model/counterpart
   critique when available and include the authorization sentence in advisor
   briefs.
8. Review changed code against the business-rule matrix, not only local syntax. Trace changed user flows, API calls, DTOs, permissions, derived state, error paths, and persistence boundaries far enough to prove whether the PR achieves the intended business behavior. Prioritize:
   - Compile, import, type, or runtime breakage.
   - Wrong behavior in changed paths.
   - Missing or contradicted business rules, acceptance criteria, role rules, status transitions, or user-visible workflow requirements.
   - Auth, data, security, API, environment, and permission contract breaks.
   - Missing tests or misleading validation for risky changed behavior.
   - Clear scoped instruction violations.
9. Apply Matt-inspired engineering checks where relevant:
   - If intent or domain language is fuzzy, ask one targeted question or state the assumption.
   - Use domain glossary and ADRs when available.
   - Prefer behavior tests through public interfaces.
   - For bugfixes, look for a reproduced failure and regression protection.
   - For architecture changes, identify shallow modules, weak test seams, or scattered concepts only when tied to the diff.
   - Turn follow-up work into vertical-slice tickets only when ticketing is requested.
10. Validate and falsify every candidate finding before reporting. For each
    surviving finding, state its **severity** (residual impact after mitigations)
    and **confidence** (how strongly the evidence supports it). Try to falsify
    the finding first; drop it if it does not survive. Drop speculative, lint-only,
    style-only, pre-existing, unscoped, or unsupported issues.
11. For GitHub PRs, immediately before posting, refresh live PR state (current
    head SHA, reviewer identity, review threads, mergeability, and required
    checks). If the head changed, a different reviewer is active, or mergeability
    changed since analysis, recompute against the new state before posting;
    author replies and head changes trigger review, not stale output. Then prepare
    a private comment plan, dedupe findings, run the contract's pre-post
    self-check, and post only approved high-confidence review comments by default.
    Prefer one submitted PR review over loose issue comments.
    - Create an inline review thread for every must-change finding on the smallest changed code range that owns the defect. Do not collapse findings into one giant review body.
    - Each substantive thread must explain: the business rule or contract being violated, the root cause in the changed code, what the code does now, a practical failure example, the negative impact of keeping the change as-is, and a concrete next step for the developer.
    - Do not limit recommendations to business decisions. When the issue is code-owned, include the exact code-level direction needed to fix it: name the function, route, payload, guard, test, migration, or component that should change, and explain why that code change solves the failing behavior.
    - Use short code snippets when they make the fix unambiguous. Prefer snippets that contrast the bad behavior with the corrected behavior, for example: "current code sends users to `/documents` without a route; replacing it with an existing route or adding the route file prevents the 404." Keep snippets scoped and do not invent full implementations when the required business decision is still unknown.
    - Use this thread shape unless repo convention requires another format:
      `Business rule / contract: ...`
      `Issue: ...`
      `Impact: ...`
      `Suggested next step: ...`
      `Code-level recommendation: ...` when useful or when the developer would otherwise need to infer the implementation.
    - If the finding spans multiple files, thread the primary changed line and name the companion files or tests needed to complete the fix.
    - Include a GitHub suggestion block when the replacement is small, complete, and safe to apply as-is. If a suggestion block is not safe because the correct business choice is unknown or the fix spans multiple files, still provide a concrete code sketch or example alternatives that show what the bad code does versus what the proposed code would solve. Never fabricate a suggestion block.
    - If a finding needs broader context than one line can hold, keep the detailed root cause and failure example in the inline thread, and use the review body only for a short transcript-free summary that points to the thread.
    - Do not include validation transcript blocks on PR surfaces. Avoid `Validation reviewed`, command-by-command pass lists, `git diff --check passed`, `git merge-tree succeeded`, `no checks reported`, or board-access caveats in PR review comments or PR bodies. Keep exact validation evidence in the operator close-out.
    - Do not add AI attribution or signatures such as `Generated with Claude Code`, model names, AI disclaimers, or watermarks.
    - If inline review APIs fail, fall back to a single request-changes or comment review body with file and line references; report the fallback.
    - If the user explicitly asks for draft/no-post mode, report findings only and mark posting as skipped.
12. When resolving addressed review threads, reply with the fix or evidence first, resolve only those threads, then re-check review state because a new head commit can invalidate prior approval and require re-review.
13. For re-review (second or later review of the same PR, follow-up after author reply or push, or queue sweep), apply the delta-first re-review contract from `pr-review-output-contract.md`: record previous reviewed SHA, current SHA, `old..new` delta, prior finding ledger and dispositions, and causally affected consumers only. Raise new blockers only if introduced/materially worsened by the delta, a concrete regression caused/exposed by the delta, or an explicitly in-scope release-critical invariant with causal proof. Unrelated or pre-existing discoveries are non-blocking follow-ups. Preserve stable finding identity; do not duplicate or reopen fixed/not-applicable/accepted-risk findings without changed facts. Fall back to a full current-head review only when the baseline is unavailable, the rewritten range is unreliable, scope/security/data/architecture materially expanded, or the user asks for a fresh review.
14. If merge-after-approval is active, perform merges after the review verdicts and report each PR as merged, not merged with reason, or blocked. Prefer the repository's standard merge method and never bypass branch protection or unresolved review requirements.
15. Produce the final report using the output contract.

