---
name: high-signal-pr-review
description: Review pull requests or diffs with a high-signal, low-false-positive workflow. Use when the user asks Codex to review a PR, inspect a diff for merge readiness, prepare review comments, check a branch before merge, or evaluate AI-generated code.
---

# High Signal PR Review

Use this skill for PR review, diff review, merge readiness, and public review comments.

## Workflow

1. Read `references/pr-review-output-contract.md` when available. If running inside a repo that vendors `agent-config-kit`, also read `skillsets/pr-review/references/pr-review-output-contract.md`, `REVIEW_AND_PR_FRAMEWORK.md`, `QUALITY_GATES.md`, and `ARCHITECTURE_AND_CODE_QUALITY.md`.
2. Preflight the PR or diff:
   - Confirm it is open and reviewable.
   - Stop or ask before continuing if it is closed, draft, obviously automated or trivial, or already reviewed by the same AI reviewer.
   - Still review AI-generated PRs when the user asks for it.
3. If the task involves existing PR comments, fetch live top-level comments, reviews, review comments, review threads, head SHA, review decision, and current checks before editing or replying. Map each comment to fixed, evidence-backed reply, not applicable, or still blocked.
4. Resolve instruction scope:
   - Root instructions.
   - Path-scoped `AGENTS.md`, `CLAUDE.md`, Cursor rules, repo docs, or local review rules that cover changed files.
   - PR template and contribution docs when relevant.
5. Read intent before details: PR title, body, linked issue, changed-file list, and author-stated tradeoffs.
6. Decide whether independent review passes are useful and available. If the platform permits sub-agents and runtime policy allows it, use bounded passes for instruction adherence, bug/security/logic, validation/test coverage, and architecture. The master thread filters and owns the final verdict.
7. Review changed code with surrounding context only as needed. Prioritize:
   - Compile, import, type, or runtime breakage.
   - Wrong behavior in changed paths.
   - Auth, data, security, API, environment, and permission contract breaks.
   - Missing tests or misleading validation for risky changed behavior.
   - Clear scoped instruction violations.
8. Apply Matt-inspired engineering checks where relevant:
   - If intent or domain language is fuzzy, ask one targeted question or state the assumption.
   - Use domain glossary and ADRs when available.
   - Prefer behavior tests through public interfaces.
   - For bugfixes, look for a reproduced failure and regression protection.
   - For architecture changes, identify shallow modules, weak test seams, or scattered concepts only when tied to the diff.
   - Turn follow-up work into vertical-slice tickets only when ticketing is requested.
9. Validate every candidate finding before reporting. Drop speculative, lint-only, style-only, pre-existing, unscoped, or unsupported issues.
10. If comment mode was not requested, report findings only. If comment mode was requested, prepare a private comment plan, dedupe findings, and post only approved high-confidence comments.
11. When resolving addressed review threads, reply with the fix or evidence first, resolve only those threads, then re-check review state because a new head commit can invalidate prior approval and require re-review.
12. Produce the final report using the output contract.

## Guardrails

- Do not post GitHub comments unless the user requested comment mode or repo policy requires it.
- Do not use web fetch for private PR content when `gh` or GitHub MCP owns the source of truth.
- Do not resolve review threads until the fix or evidence has landed and each addressed thread has a response.
- Do not flag issues the repo linter would catch unless they are blocking by repo policy or cause real behavior failure.
- Do not give broad quality advice unless it is tied to changed behavior and materially affects correctness, safety, testability, or maintainability.
- Do not claim tests or CI passed unless you ran them or inspected their actual output.
- Do not approve a PR with unresolved security, data, runtime, or required-validation uncertainty.

## Output

Return findings first, ordered by severity. Include:

- Findings with file and line references.
- Open questions.
- Validation reviewed.
- Review scope and instructions applied.
- Dropped candidates when useful.
- Residual risk.
