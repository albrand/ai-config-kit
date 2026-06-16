# Review And PR Framework

Use this framework for code reviews, self-reviews, and PR preparation.

## Review Posture

Lead with findings. Prioritize:

1. Bugs and behavioral regressions.
2. Security, permission, and data-isolation risks.
3. Broken runtime contracts.
4. Missing tests for changed behavior.
5. Architecture or maintainability risks.
6. Performance regressions.
7. Documentation or release gaps.

If there are no findings, say that clearly and list residual risk or unverified checks.

## Review Scope

Before reviewing:

- Resolve the changed files.
- Identify the intended behavior.
- Identify source-of-truth docs.
- Identify runtime contracts.
- Identify relevant tests.
- Keep review scoped to the changed surface unless the user requests broader review.

## High-Signal PR Review Workflow

Use this workflow when reviewing a GitHub PR or equivalent diff where comments may be posted publicly.

Executable entrypoints:

- Codex skill: `skillsets/pr-review/codex/high-signal-pr-review/SKILL.md`
- Claude Code command: `skillsets/pr-review/claude/commands/code-review.md`
- Output contract: `skillsets/pr-review/references/pr-review-output-contract.md`

1. Preflight before review:
   - Confirm the PR or diff is open for review.
   - Stop or ask before continuing if it is closed, draft, obviously automated/trivial, or already reviewed by the same AI reviewer.
   - Still review AI-generated PRs when the user requests it.
2. Resolve instruction scope:
   - Identify root and path-scoped instruction files that apply to changed files, such as `CLAUDE.md`, `AGENTS.md`, Cursor rules, repo docs, or local review rules.
   - Apply only the instruction files whose path scope covers the changed file.
3. Summarize intent:
   - Read the PR title, description, linked issue, and changed-file list before reviewing details.
   - Keep author intent visible so reviewers do not flag intentional tradeoffs as bugs.
4. Run independent review passes when the tool supports it:
   - Two compliance passes for scoped instruction adherence.
   - One or more bug/security/logic passes focused on introduced code and the diff itself.
   - Keep style, subjective improvements, and linter-only concerns out unless the repo rules explicitly require them.
5. Validate candidate issues:
   - Re-check every candidate bug, logic error, security issue, or instruction violation before reporting it.
   - Drop findings that are speculative, pre-existing, lint-only, unscoped, or not reproducible from the diff and allowed context.
6. Report and post:
   - Report only high-confidence, high-signal issues.
   - Deduplicate findings.
   - For GitHub PRs, post a submitted review by default unless the user explicitly requested draft/no-post mode or posting is blocked.
   - Use inline review threads for changed code when possible, with exact file/line context and links using the full commit SHA when linking to GitHub.
   - Include the failing contract or behavior, runtime impact, and concrete fix direction in the review thread.
   - Use committable suggestion blocks only when the suggestion fully fixes the issue without hidden follow-up work.
   - If inline review APIs fail, fall back to one submitted review body with file/line references and state the fallback.

## Existing Review Comments And Re-Review

Use this when the user asks to address, respond to, or resolve existing PR comments.

- Refresh live PR state before editing: top-level comments, submitted reviews, review comments, review threads, head SHA, merge or review decision, and current checks.
- Build a comment action table: fixed, needs evidence-backed reply, not applicable, or still blocked. Do not silently ignore earlier feedback.
- Patch only the scoped issue unless the comment exposes a broader correctness or safety gap.
- Reply to each applicable comment or thread after the fix is pushed or the evidence is verified. Prefer thread replies for review threads and a top-level summary only for cross-thread status.
- Resolve only threads that were actually addressed. Leave unresolved threads open when they need reviewer input, product approval, or broader follow-up work.
- Re-check checks and deployment status after pushing. Treat older bot comments as historical when a newer check or deployment supersedes them.
- Re-check review state after every head change. A new commit can invalidate an earlier approval, so request re-review when the platform reports review required.

High-signal means:

- The code will fail to compile, parse, import, or resolve.
- The code will definitely produce wrong behavior for the changed path.
- The change breaks an auth, data, security, runtime, or API contract.
- The change clearly violates a scoped instruction and the exact rule can be cited.

Do not flag:

- Pedantic style concerns.
- General code quality suggestions that are not tied to changed behavior.
- Issues only a linter would catch.
- Concerns that require unsupported assumptions about future input or state.
- Pre-existing problems unless the PR makes them materially worse.

## Engineering Pattern Additions

Use these additions when they are relevant to the changed surface:

- If PR intent, domain language, or acceptance criteria are ambiguous, ask one targeted question or state the assumption before continuing.
- Use domain glossary files, `CONTEXT.md`, `CONTEXT-MAP.md`, and ADRs when available. Do not re-litigate an ADR unless the diff exposes real friction.
- For bugfix PRs, look for a reproduced failure and regression protection. A test, script, replay, or smoke path can be enough if it proves the original failure no longer reproduces.
- Prefer tests that verify behavior through public interfaces. Treat tests coupled to private implementation details as weak evidence unless the repo intentionally tests that layer.
- When architecture is in scope, look for shallow pass-through modules, scattered concepts, weak test seams, and interfaces whose invariants are unclear. Report only issues tied to changed behavior or merge risk.
- When follow-up work is requested, split it into vertical slices that are independently grabbable, demoable or verifiable, and sized for one PR.

## Interactive Review Mode

Use this mode when repo instructions or the user request an interactive
section-by-section review instead of a single findings report.

Before starting, ask the user to choose the review depth:

- `1/ BIG CHANGE`: interactive section-by-section review with at most four top
  issues per section: Architecture, Code Quality, Tests, Performance.
- `2/ SMALL CHANGE`: interactive review with exactly one question per review
  section.

Use the platform's structured user-question tool when available. If the
platform names that tool `AskUserQuestion`, use it for the decision prompt. If
the active tool exposes a different structured question mechanism, use the
closest equivalent; otherwise ask a direct textual question and wait.

For each issue or recommendation, provide two or three options and include
"do nothing" when reasonable. Label options with letters. For each option,
state implementation effort, risk, impact on other code, and maintenance
burden. Put the recommended option first in the decision prompt, and include
both issue number and option letter in each structured option.

Pause after each review section and wait for feedback before moving to the next
section.

## Review Criteria

Check:

- Request fidelity: change matches the ask.
- Source-of-truth fidelity: change matches accepted docs or designs.
- Runtime contract: inputs, outputs, auth, permissions, flags, env, cache, errors.
- Complexity: changed code remains understandable.
- Architecture: responsibilities stay in the right modules.
- State flow: no stale state, duplicate reloads, or cache drift.
- Data flow: no overfetching, missing filters, or broken pagination.
- Security: boundaries preserved.
- Tests: right layer and meaningful assertions.
- Validation: commands actually ran and results are truthful.

## Finding Format

Use:

```md
1. <path>:<line>
   <What is wrong and why it matters.>
   Question: <direct question if intent is unclear>
   Recommendation: <specific fix or options>
```

Findings should include file references and be ordered by severity.

## Self-Review Before Completion

After editing, review your own diff:

- Re-read changed files.
- Compare against source of truth.
- Check architecture boundaries.
- Check state and data flow.
- Check security boundary.
- Check tests are behavior-focused.
- Check validation commands and outcomes.
- Fix safe issues before final response.
- Report issues that need broader scope or a decision.

## PR Preparation

Prepare PR bodies from real evidence, not memory.

Read:

- Actual diff.
- Changed files.
- Tests and validation output.
- Repo PR template.
- Release or deployment docs when relevant.

PR body should include:

- Problem.
- Approach.
- Important tradeoffs.
- Files or areas changed.
- Validation run.
- Deployment or operational impact.
- Rollback path.
- Residual risk.

Do not leave template sections blank. Use `N/A` if a section does not apply.

## Approval Standard

Approve or call ready only when:

- Changed behavior matches the request and source of truth.
- Runtime contracts are preserved.
- No blocking security or data risks remain.
- Focused validation supports the changed behavior.
- Required checks passed or gaps are explicitly non-blocking.
- Residual risk is documented.

Request changes or mark not ready when:

- The changed behavior is broken.
- Security or data boundaries are uncertain.
- Runtime contracts are broken.
- Required tests are missing for risky behavior.
- Validation is misleading or insufficient.
- The implementation hides scope expansion.

## Review Output Template

```md
Findings:

1. <finding>
2. <finding>

Open questions:

- <question or "None">

Validation reviewed:

- <command/output reviewed>

Residual risk:

- <risk or "None identified">
```

## PR Body Template

```md
## Problem

<What gap or defect this change addresses.>

## Approach

<What changed and why this approach.>

## Changed Surface

- <area/file>

## Validation

- <command>: <status>

## Deployment / Operations

<Impact, migration, env, monitoring, or N/A.>

## Rollback

<How to revert or contain.>

## Residual Risk

<Known gaps or "None identified".>
```
