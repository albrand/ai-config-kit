# PR Review Skillset

This skillset turns the shared review doctrine into executable Codex and Claude Code workflows.

Use it when the user asks for a PR review, diff review, merge-readiness review, AI reviewer setup, or high-signal review comments.

## Entry Points

- Codex: `skillsets/pr-review/codex/high-signal-pr-review/SKILL.md`
- Claude Code: `skillsets/pr-review/claude/commands/code-review.md`
- Shared output contract: `skillsets/pr-review/references/pr-review-output-contract.md`

## Imported Patterns

This skillset adapts public review and engineering practices into neutral framework language:

- Anthropic Claude Code review workflow: preflight stop checks, scoped instruction discovery, parallel independent review passes, candidate validation, deduplication, and submitted PR reviews with inline threads by default for GitHub PRs.
- Matt Pocock engineering patterns: grill unclear requirements one question at a time, use domain glossary and ADRs when available, prefer behavior tests through public interfaces, diagnose before fixing, find deep-module architecture opportunities, and break follow-up work into vertical slices.

Do not clone public skills wholesale into project repos. Keep the local workflow source-traceable, small, and adapted to the repo's own instructions.

## Safety

- For GitHub PRs, post a submitted review by default unless the user explicitly requested draft/no-post mode or posting is blocked.
- Prefer inline review threads over loose issue comments, and fall back to a single review body only when inline posting is unavailable.
- Do not review closed, draft, trivial automated, or already-reviewed PRs unless the user explicitly asks.
- Do not flag speculative, lint-only, style-only, pre-existing, or unscoped issues.
- Do not use committable suggestion blocks unless the suggestion fully fixes the issue.
- Do not claim validation passed unless it was actually run or inspected.
