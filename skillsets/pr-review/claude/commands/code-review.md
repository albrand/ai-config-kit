---
description: Review a pull request or diff with high-signal filtering, scoped instructions, validated findings, and optional GitHub comments.
argument-hint: [PR number, URL, branch, diff path, optional --comment]
allowed-tools: Bash(gh pr view:*), Bash(gh pr diff:*), Bash(gh pr list:*), Bash(gh pr comment:*), Bash(gh issue view:*), Bash(gh search:*), Bash(git diff:*), Bash(git status:*), Bash(git rev-parse:*), mcp__github_inline_comment__create_inline_comment
---

# Code Review

Provide a high-signal code review for the given pull request or diff.

User input:

`$ARGUMENTS`

Use normal Claude Code capabilities. Prefer `gh` CLI or GitHub MCP for GitHub PR truth. Do not post comments unless `--comment` is included or the user explicitly requested comment mode.

## Workflow

1. Load `~/.claude/pr-review-output-contract.md` when available. If running inside a repo that vendors `agent-config-kit`, also load `REVIEW_AND_PR_FRAMEWORK.md`, `QUALITY_GATES.md`, `ARCHITECTURE_AND_CODE_QUALITY.md`, and `skillsets/pr-review/references/pr-review-output-contract.md`.
2. Create a todo list before starting.
3. Preflight:
   - Confirm the PR or diff is open and reviewable.
   - Stop or ask before continuing if it is closed, draft, obviously automated or trivial, or already reviewed by the same AI reviewer.
   - Still review AI-generated PRs when the user asks for it.
4. Resolve instruction scope:
   - Root `CLAUDE.md` or `AGENTS.md`.
   - Path-scoped instruction files for changed files.
   - PR template and repo review rules.
5. Read PR intent before details: title, body, linked issue, changed-file list, and author-stated tradeoffs.
6. Use independent agents when useful and available:
   - One or two instruction-compliance passes.
   - One bug/security/logic pass focused on changed code.
   - One validation/test/architecture pass for risky changes.
   - Tell each agent the PR title, description, changed-file list, scope, and output cap.
7. Review candidates only against the changed surface and applicable instructions. Flag only:
   - Compile, parse, import, type, or runtime breakage.
   - Definitely wrong behavior.
   - Auth, data, security, API, runtime, or environment contract breaks.
   - Required validation missing for risky changed behavior.
   - Clear scoped instruction violations.
8. Apply engineering checks inspired by Matt Pocock's public skills when relevant:
   - Ask one targeted question if intent or domain language is ambiguous.
   - Use domain glossary and ADRs when present.
   - Prefer behavior tests through public interfaces.
   - For bugfix PRs, check for reproduced failure and regression protection.
   - For architecture changes, identify shallow modules, weak test seams, or scattered concepts only when tied to the diff.
   - Convert follow-ups into vertical-slice tickets only when ticketing is requested.
9. Validate every candidate finding before reporting. Drop false positives, speculative issues, lint-only concerns, style-only concerns, pre-existing issues, and unsupported assumptions.
10. Report findings to the terminal or final response using the output contract.
11. If `--comment` is not present, stop without posting comments.
12. If `--comment` is present:
   - Create a private list of comments first.
   - Post at most one comment per unique issue.
   - Prefer inline comments on changed code.
   - Use a committable suggestion block only when it fully fixes the issue.
   - If no issues are found and a summary comment is requested, post a short no-issues summary.

## Output

Use the final report shape from `pr-review-output-contract.md`. Findings first, then open questions, validation reviewed, review scope, dropped candidates when useful, and residual risk.
