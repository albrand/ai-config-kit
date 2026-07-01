---
name: high-signal-pr-review
description: Review pull requests or diffs with a business-rule-first, high-signal, low-false-positive workflow, inline code threads, and a board-backed regression gate. Use when the user asks Codex to review a PR, inspect a diff for merge readiness, prepare review comments, check a branch before merge, evaluate AI-generated code, or improve developer-facing PR feedback.
---

# High Signal PR Review

Use this skill for PR review, diff review, merge readiness, and public review comments.
For GitHub pull requests, treat "review" as analyze and post the review by default.
Do not split analysis from posting unless the user explicitly asks for draft/no-post mode,
the target is not a postable PR, or posting is blocked.

## Workflow

1. Read `references/pr-review-output-contract.md` when available. If running inside a repo that vendors `agent-config-kit`, also read `skillsets/pr-review/references/pr-review-output-contract.md`, `REVIEW_AND_PR_FRAMEWORK.md`, `QUALITY_GATES.md`, and `ARCHITECTURE_AND_CODE_QUALITY.md`.
2. Preflight the PR or diff:
   - Confirm it is open and reviewable.
   - Stop or ask before continuing if it is closed, draft, obviously automated or trivial, or already reviewed by the same AI reviewer.
   - Still review AI-generated PRs when the user asks for it.
   - For queue sweeps, enumerate live open PRs plus any review-required PRs and PRs whose latest non-bot comment or review-thread reply is not from the active reviewer. Treat an author reply after any review or change-request thread as an addressed-review signal and re-review the current head instead of reusing stale blocker text. Deduplicate by PR number, skip closed PRs, and record draft or access-blocked PRs instead of silently dropping them.
   - When the user has authorized merge-after-approval, merge PRs that are already approved or that this review approves only after live mergeability, required checks, unresolved conversations, branch currency, and reviewer identity constraints are verified. Do not merge self-authored PRs, draft PRs, blocked PRs, PRs with unresolved high-signal findings, or PRs whose approval/merge state cannot be verified.
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
6. Demand authoritative ticket-board access before readiness judgment.
   - For Jira-backed repositories, ask imperatively for Jira board access; for non-Jira repositories, ask for the configured equivalent board or a current board export.
   - Inventory all visible board tickets, not only the PR's linked issue: key, title, type, status, sprint/release, component/area, acceptance criteria, linked PR/release evidence, and QA/Done evidence when present.
   - Check the diff against the entire inventory, especially current, adjacent, QA, Done, released, and previously working tickets that share files, routes, contracts, data, permissions, or user workflows with the PR.
   - Treat plausible regression of already working board-backed behavior as a Blocker until disproven with code evidence and targeted validation.
   - Missing board access, stale export, incomplete inventory, or missing PR-to-ticket traceability means **Board regression gate blocked / NOT READY**. Do not approve, merge, or call the PR regression-safe.
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
10. Validate every candidate finding before reporting. Drop speculative, lint-only, style-only, pre-existing, unscoped, or unsupported issues.
11. For GitHub PRs, prepare a private comment plan, dedupe findings, and post only approved high-confidence review comments by default. Prefer one submitted PR review over loose issue comments.
    - Create an inline review thread for every must-change finding on the smallest changed code range that owns the defect. Use the review body only for summary, cross-cutting context, or findings that cannot be attached to a changed line.
    - Each thread must explain: the business rule or contract being violated, what the code does now, the negative impact of keeping the change as-is, and a concrete next step for the developer.
    - Do not limit recommendations to business decisions. When the issue is code-owned, include the exact code-level direction needed to fix it: name the function, route, payload, guard, test, migration, or component that should change, and explain why that code change solves the failing behavior.
    - Use short code snippets when they make the fix unambiguous. Prefer snippets that contrast the bad behavior with the corrected behavior, for example: "current code sends users to `/documents` without a route; replacing it with an existing route or adding the route file prevents the 404." Keep snippets scoped and do not invent full implementations when the required business decision is still unknown.
    - Use this thread shape unless repo convention requires another format:
      `Business rule / contract: ...`
      `Issue: ...`
      `Impact: ...`
      `Suggested next step: ...`
      `Code-level recommendation: ...` when useful or when the developer would otherwise need to infer the implementation.
    - If the finding spans multiple files, thread the primary changed line and name the companion files or tests needed to complete the fix.
    - Include a GitHub suggestion block when the replacement is small, complete, and safe to apply as-is. If a suggestion block is not safe because the correct business choice is unknown, still provide a concrete code sketch or example alternatives that show what the bad code does versus what the proposed code would solve.
    - If a finding needs broader context than one line can hold, put the full explanation in the review body and leave a concise inline thread on the changed line.
    - If inline review APIs fail, fall back to a single request-changes or comment review body with file and line references; report the fallback.
    - If the user explicitly asks for draft/no-post mode, report findings only and mark posting as skipped.
12. When resolving addressed review threads, reply with the fix or evidence first, resolve only those threads, then re-check review state because a new head commit can invalidate prior approval and require re-review.
13. If merge-after-approval is active, perform merges after the review verdicts and report each PR as merged, not merged with reason, or blocked. Prefer the repository's standard merge method and never bypass branch protection or unresolved review requirements.
14. Produce the final report using the output contract.

## Guardrails

- For GitHub PRs, post the review unless the user explicitly requests draft/no-post mode or posting is blocked.
- Do not post loose GitHub issue comments for PR findings when a submitted PR review or inline review thread is possible.
- Do not use web fetch for private PR content when `gh` or GitHub MCP owns the source of truth.
- Do not resolve review threads until the fix or evidence has landed and each addressed thread has a response.
- Do not flag issues the repo linter would catch unless they are blocking by repo policy or cause real behavior failure.
- Do not give broad quality advice unless it is tied to changed behavior and materially affects correctness, safety, testability, or maintainability.
- Do not review PRs as generic code diffs when the stated goal is business behavior. First identify the business rules and acceptance criteria the PR claims to satisfy, then review the code against those rules.
- Do not leave must-change feedback only in the summary when a changed code line owns the issue; create an inline thread with reason, negative impact, and suggested next step.
- Do not leave developers with only product-level options when the defect is code-owned; add code-level recommendations, snippets, or safe suggestion blocks that make the intended fix mechanically clear.
- Do not claim tests or CI passed unless you ran them or inspected their actual output.
- Do not approve a PR with unresolved security, data, runtime, or required-validation uncertainty.
- Do not approve or mark a PR ready when the board-backed regression gate is blocked, incomplete, or shows a plausible regression.

## Output

Return findings first, ordered by severity. Include:

- Findings with file and line references.
- Business rules checked, their sources, and whether the PR satisfies them.
- Open questions.
- Validation reviewed.
- Board checked, inventory scope/date, matched tickets, and protected behavior checked.
- Review scope and instructions applied.
- Dropped candidates when useful.
- Residual risk.
