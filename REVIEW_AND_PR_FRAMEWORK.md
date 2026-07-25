# Review And PR Framework

Use this framework for code reviews, self-reviews, and PR preparation.

## Review Posture

Lead with findings. Prioritize:

1. Bugs and behavioral regressions.
2. Security, permission, and data-isolation risks.
3. Broken runtime contracts.
4. Missing ownership-gated test evidence for changed behavior (see `TEST_OWNERSHIP.md`).
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

The output contract is mandatory and canonical for PR reviews, merge-readiness
comments, public review comments, and PR bodies. Tool-specific entrypoints must
load it instead of restating or weakening the public review surface rules.

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
   - Use inline review threads for changed code when possible, with exact file/line context and links using the full commit SHA when linking to GitHub. Do not replace threadable findings with one giant review body.
   - Include the failing contract or behavior, root cause in the changed code, a practical failure example, runtime impact, and concrete fix direction in each substantive review thread.
   - Use committable suggestion blocks when the replacement is small, complete, and safe to apply as-is. Do not fabricate suggestion blocks for findings that need broader design or multi-file work.
   - Keep PR review comments and PR bodies transcript-free: no `Validation reviewed` blocks, command-by-command pass lists, `git diff --check passed`, `git merge-tree succeeded`, `no checks reported`, or board-access caveats. Exact validation evidence belongs in the operator close-out.
   - Do not add AI attribution or generated-by signatures to PR surfaces.
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

## Delta-First Re-Review Contract

A **re-review** is any second or later review of the same PR, a follow-up review
after the author replied or pushed, or a queue sweep that revisits a previously
reviewed head. Re-review is **delta-first**, not full-current-head by default.
The canonical, normative form of this contract lives in
`skillsets/pr-review/references/pr-review-output-contract.md`; tool-specific
entrypoints must load it instead of restating it.

### Re-Review Inputs

Record before judging:

- Previous reviewed SHA (the baseline).
- Current SHA (the head under re-review).
- The `old..new` delta being re-reviewed.
- Prior finding ledger and dispositions (fixed, accepted-risk, not-applicable,
  wontfix, or still-open) for this PR.
- Only the direct and transitive consumers causally affected by the delta.

### New Blockers

In a delta-first re-review, raise a **new blocker** only when it meets at least
one condition:

- Introduced or materially worsened by the delta under review.
- A concrete regression caused or exposed by the delta.
- An explicitly in-scope, release-critical invariant with causal proof tying it
  to the delta.

Unrelated or pre-existing discoveries are **non-blocking follow-ups**. Report
them separately; do not let them expand the blocking scope of the re-review.

### Board Inventory In Re-Review

Board inventory cannot expand re-review blocking scope without a **causal delta
path** to the changed surface. A plausible regression against protected
board-backed behavior is a blocker only when the delta can reach that behavior;
otherwise it is a follow-up. Missing board access must not suppress concrete code
findings, and must not block unrelated code findings either (see the proportional
board rule in `GLOBAL_AGENTS.md`).

### Finding Identity

Preserve stable finding identity across re-reviews. Do not duplicate, reopen, or
re-report a finding already disposed as fixed, not-applicable, or accepted-risk
unless the facts changed. Drop fixed findings from the active ledger; track only
what remains open and what the new delta newly introduces or worsens.

### Full-Current-Head Fallback

Fall back to a **full current-head review** only when:

- The baseline SHA is unavailable or unreachable.
- The rewritten range makes comparison unreliable (for example, a force-push or
  squash that destroys the delta).
- Scope, security, data, or architecture materially expanded beyond the delta.
- The user explicitly asks for a fresh full review.

State the fallback reason in the review. Outside these cases, keep the review
delta-first.

### Re-Review Scenarios

- **Fixed blocker:** the prior blocker was resolved. Drop it; do not reopen
  without changed facts. Require new evidence only for what the new delta affects.
- **Delta-caused adjacent regression:** the follow-up commit changes a helper the
  prior delta's callers use. There is a causal path, so it is in scope; require
  evidence for that path only.
- **Unrelated legacy defect:** the delta never touched it. Report as a
  non-blocking follow-up; do not block the delta.
- **Unavailable baseline:** the prior SHA is unreachable. Fall back to a full
  current-head review and state the reason.
- **Materially expanded scope:** the follow-up rewrites an auth boundary or data
  path. A full current-head review is justified and durable protection may be
  required anew.

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

For public PR review comments, use the stricter inline thread shape in
`skillsets/pr-review/references/pr-review-output-contract.md`: root cause,
practical failure example, impact, and suggestion-if-applicable on the smallest
owning changed range.

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
- App-value details that reviewers should understand.
- Linked ticket, when present.
- Tests, validation output, release docs, and deployment docs only for the
  operator close-out, not for PR body sections.

PR body must include only:

- Summary of what was done.
- What the PR changes, why it changes that, and what value it adds to the app;
  this must add concrete, non-repetitive details beyond the summary.
- Ticket reference, only when one applies.

Do not add sections for approach, validation, deployment notes, risks,
follow-ups, checklists, rollback, residual risk, testing, or command logs. Keep
that operator evidence in the close-out to the user, not in the PR body.

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

Operator validation:

- <command/output reviewed; do not copy this block into PR surfaces>

Residual risk:

- <risk or "None identified">
```

## PR Body Template

```md
## Summary

<what was done>

## Changes and value

<what changed, why, and what value it adds to the app>

## Ticket

<ticket reference; omit this section when none applies>
```
