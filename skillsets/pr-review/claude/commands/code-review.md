---
description: Review a pull request or diff with high-signal filtering, scoped instructions, validated findings, and default submitted GitHub reviews.
argument-hint: [PR number, URL, branch, diff path, optional --no-post]
allowed-tools: Bash(gh api:*), Bash(gh pr checks:*), Bash(gh pr comment:*), Bash(gh pr diff:*), Bash(gh pr edit:*), Bash(gh pr list:*), Bash(gh pr review:*), Bash(gh pr view:*), Bash(gh issue view:*), Bash(gh search:*), Bash(git diff:*), Bash(git status:*), Bash(git rev-parse:*), mcp__github_inline_comment__create_inline_comment
---

# Code Review

Provide a high-signal code review for the given pull request or diff.

User input:

`$ARGUMENTS`

Use normal Claude Code capabilities. Prefer `gh` CLI or GitHub MCP for GitHub PR truth. For GitHub PRs, treat review as analyze and submit the review by default. Do not split analysis from posting unless `--no-post` is included, the target is not a postable PR, or posting is blocked.

## Workflow

1. Load `~/.claude/pr-review-output-contract.md` when available. If running inside a repo that vendors `agent-config-kit`, also load `REVIEW_AND_PR_FRAMEWORK.md`, `QUALITY_GATES.md`, `ARCHITECTURE_AND_CODE_QUALITY.md`, and `skillsets/pr-review/references/pr-review-output-contract.md`.
2. Create a todo list before starting.
3. Preflight:
   - Confirm the PR or diff is open and reviewable.
   - Stop or ask before continuing if it is closed, draft, obviously automated or trivial, or already reviewed by the same AI reviewer.
   - Still review AI-generated PRs when the user asks for it.
4. If the task involves existing PR comments, fetch live top-level comments, reviews, review comments, review threads, head SHA, review decision, and current checks before editing or replying. Map each comment to fixed, evidence-backed reply, not applicable, or still blocked.
5. Resolve instruction scope:
   - Root `CLAUDE.md` or `AGENTS.md`.
   - Path-scoped instruction files for changed files.
   - PR template and repo review rules.
6. Read PR intent before details: title, body, linked issue, changed-file list, and author-stated tradeoffs.
7. Use independent agents when useful and available:
   - One or two instruction-compliance passes.
   - One bug/security/logic pass focused on changed code.
   - One validation/test/architecture pass for risky changes.
   - Tell each agent the PR title, description, changed-file list, scope, and output cap.
8. Review candidates only against the changed surface and applicable instructions. Flag only:
   - Compile, parse, import, type, or runtime breakage.
   - Definitely wrong behavior.
   - Auth, data, security, API, runtime, or environment contract breaks.
   - Required validation missing for risky changed behavior.
   - Clear scoped instruction violations.
9. Apply engineering checks inspired by Matt Pocock's public skills when relevant:
   - Ask one targeted question if intent or domain language is ambiguous.
   - Use domain glossary and ADRs when present.
   - Prefer behavior tests through public interfaces.
   - For bugfix PRs, check for reproduced failure and regression protection.
   - For architecture changes, identify shallow modules, weak test seams, or scattered concepts only when tied to the diff.
   - Convert follow-ups into vertical-slice tickets only when ticketing is requested.
10. Validate every candidate finding before reporting. Drop false positives, speculative issues, lint-only concerns, style-only concerns, pre-existing issues, and unsupported assumptions.
11. Create a private comment plan before posting; dedupe findings; prefer one submitted PR review over loose issue comments.
12. For GitHub PRs, post approved high-confidence review comments by default unless `--no-post` is present or posting is blocked.
13. Prefer inline review threads on the smallest changed code range that owns the defect. Include the failing contract or behavior, runtime impact, concrete fix direction, and a committable suggestion block only when it fully fixes the issue. If inline review APIs fail, fall back to one submitted request-changes/comment review body with file/line references and state the fallback.
14. When resolving addressed review threads, reply with the fix or evidence first, resolve only those threads, then re-check review state because a new head commit can invalidate prior approval and require re-review.

## Output

Use the final report shape from `pr-review-output-contract.md`. Findings first, then open questions, validation reviewed, review scope, dropped candidates when useful, and residual risk.
