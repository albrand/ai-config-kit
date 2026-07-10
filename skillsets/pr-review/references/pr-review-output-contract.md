# PR Review Output Contract

Load this reference before producing final artifacts for `high-signal-pr-review`, `/code-review`, PR review comments, merge-readiness reviews, or PR bodies.

This file is the normative source for public PR-review output. Codex, Claude
Code, opencode/GLM, and any other AI agent entrypoint must load and obey this
contract before reviewing a PR or preparing a PR body. Do not fork these rules
into tool-specific summaries; reference this contract from each entrypoint.

PR surfaces include inline review threads, submitted review bodies, top-level PR
comments, PR bodies, and merge-readiness comments. Operator close-outs are
separate and may record exact validation evidence for the user.

Never add AI attribution on PR surfaces: no model names, no "Generated with..."
footer, no "Claude Code" signature, no AI disclaimer, and no watermark.

## PR Body Contract

When preparing, editing, or replacing a PR body, use only this shape:

```md
## Summary

<what was done>

## Changes and value

<what changed, why it changed, and what value it adds to the app>

## Ticket

<ticket reference>
```

Omit `## Ticket` when no ticket applies. Do not add sections named
`Approach`, `Validation`, `Deployment Notes`, `Deployment / Operations`,
`Risks`, `Follow-ups`, `Checklist`, `Rollback`, `Residual Risk`, `Testing`, or
similar operator-log headings. Do not paste command lists, validation
transcripts, deployment logs, checklists, board-access caveats, or AI
signatures into the PR body. Keep exact validation, rollout, risk, and follow-up
details in the operator close-out unless the user explicitly asks to put a
specific item in the PR body.

The `Changes and value` section should not repeat the summary. Use it to name
the concrete product/code details that matter to reviewers: notable flows,
runtime behaviors, persistence/audit improvements, admin/customer UX, delivery
paths, or other implementation details that explain why the app is better after
the PR.

Repo-local PR templates take precedence. When a repository template defines
required sections, honor those required project sections while keeping each
section transcript-free: no command logs, validation transcripts, board-access
caveats, or AI attribution. The minimal-body rule above applies only to sections
the template does not mandate.

## Source Evidence

Record:

- PR identifier or diff source.
- PR title, description, linked issue, and author intent.
- Business rules, acceptance criteria, and product/user workflows the PR is meant to satisfy, with source links or file references.
- Changed file list.
- Applicable instruction files and their scope.
- Validation output inspected.
- External systems used or unavailable.
- Whether posting is expected, skipped, or blocked.
- Existing issue comments, review comments, and review threads inspected when the task is to address or respond to PR feedback.
- Review state after the latest head change, including whether re-review is required.

## Preflight

Before reviewing, decide whether to continue:

| Check                                       | Stop Unless User Overrides                              |
| ------------------------------------------- | ------------------------------------------------------- |
| PR closed                                   | Yes                                                     |
| PR draft                                    | Yes                                                     |
| Obviously automated or trivial              | Yes                                                     |
| Same authenticated reviewer already reviewed the current head | Stop only if no author reply and no head change since that review; re-review after an author reply or a new head |
| Missing diff access                         | Yes                                                     |
| Missing repo instructions for changed paths | No, continue with known instructions and report the gap |

Still review AI-generated PRs when the user explicitly requests review.

The prior-review stop is observable and precise: do not stop merely because an
earlier review exists. Stop only when the same authenticated reviewer identity
already reviewed the current head SHA and no author activity or head change has
occurred since. Re-review when the author replies to a review/change-request
thread or when a new head commit lands. When no same-reviewer same-head review
exists, proceed and review the current head.

## Review Passes

Use the strongest practical version supported by the active tool:

1. Intent pass: title, body, linked issue, changed-file list.
2. Business-rule pass: ticket acceptance criteria, user workflow, role rules, status/data lifecycle, API/backend contracts, previously working behavior, and non-goals.
3. Instruction pass: root and path-scoped instructions that apply to changed files.
4. Bug and contract pass: changed code only, with surrounding context as needed.
5. Security and data pass: auth, permissions, isolation, input/output, secrets, logging.
6. Test and validation pass: behavior coverage and evidence quality.
7. Architecture pass: boundaries, domain language, ADR conflicts, deep-module opportunities.

When sub-agents are available and approved by runtime policy, use independent bounded passes. Keep the master thread responsible for filtering and final judgment.

Review passes should challenge prior review comments, directives, journals,
memories, cached conclusions, and project patterns as evidence rather than
authority. For architecture or readiness advisor briefs, include the
authorization sentence required by the framework.

## High-Signal Finding Bar

Report only findings that meet at least one condition:

- The changed code will fail to compile, parse, import, or resolve.
- The changed path will definitely produce wrong behavior.
- The implementation does not satisfy, contradicts, or silently narrows a business rule, acceptance criterion, workflow, role rule, state transition, or previously working board-backed behavior the PR is supposed to preserve.
- The change breaks an auth, data, security, runtime, API, or environment contract.
- The change violates an applicable scoped instruction and the exact rule can be cited.
- Required validation is missing for a risky behavior introduced by the PR.

Drop:

- Style-only concerns.
- Lint-only concerns unless repo policy makes them blocking.
- Speculative future issues.
- Pre-existing issues unless the PR makes them materially worse.
- General quality suggestions not tied to changed behavior.
- Business concerns that cannot be tied to a source, changed behavior, or a specific acceptance rule.
- Findings that require unsupported assumptions.

Every reported finding must carry, on its own: the source rule or acceptance
criterion it violates; changed-code causality (the exact changed path/state/guard
that causes the failure); a practical failure example; validation or
falsification (how the claim was checked and what would refute it); the owning
changed range it is posted on; severity and confidence with a one-line basis;
and a concrete fix direction. Findings missing any of these, or that are
unsupported, speculative, or merely pre-existing without being made materially
worse, are dropped before posting.

## Business Rule Review Matrix

Before finalizing the review, build and use a compact matrix:

| Business rule / acceptance criterion | Source | Changed code | Expected behavior | Evidence |
| --- | --- | --- | --- | --- |

Use product tickets, board inventory, PR description, domain docs, backend
controllers/DTOs, API schemas, screenshots, existing tests, and current code as
sources. If a source is unavailable and the gap affects readiness, mark the
review `NEEDS DISCUSSION` or `Board regression gate blocked / NOT READY`; do not
approve based on generic code quality.

## Code Findings vs. Board-Backed Readiness

Keep these two outputs separate:

- **Code findings** — compile/runtime breakage, wrong changed-path behavior,
  broken auth/data/security/API/env contracts, missing required validation, and
  scoped-instruction violations validated from the diff. These are reported
  regardless of board access. Missing board access must never suppress a useful,
  validated code finding.
- **Board-backed merge/approval-readiness** — requires ticket-board evidence.
  Missing board access, a stale export, an incomplete inventory, or missing
  PR-to-ticket traceability blocks approval, merge, and any "ready/regression-safe"
  verdict, but it does not block reporting the code findings above.

Board inventory scope: inventory all visible board tickets when a board source is
available. When no broader board source exists, scope the inventory to the linked
ticket plus demonstrably impacted tickets (shared files, routes, contracts, data,
permissions, or user workflows) and state that narrower scope. Always report
board name/scope/date, the tickets matched to the change, and the protected
behavior checked for regression.

## Matt-Inspired Review Additions

Use these additions only when relevant to the changed surface:

- If the PR intent is ambiguous, ask one targeted question or state the assumption before reviewing.
- Use the repo's domain glossary, `CONTEXT.md`, `CONTEXT-MAP.md`, and ADRs when present.
- Prefer tests that verify observable behavior through public interfaces.
- For bugfix PRs, check whether the original failure was reproduced and locked with a regression test or equivalent feedback loop.
- Look for shallow pass-through modules, scattered domain concepts, or weak test seams when the PR touches architecture.
- Convert follow-up work into vertical-slice tickets, not horizontal chores, when ticketing is requested.

## Posting Mode

Default for GitHub PRs: analyze and submit the review. Do not require a separate
"post" instruction. Treat "review this PR" as permission to publish the review
unless the user explicitly asks for draft/no-post mode.

When posting:

- Prepare a private comment plan first.
- Post at most one comment per unique issue.
- Create inline review threads on changed code. Every must-change finding needs
  an inline thread unless no changed line owns the issue.
- Start review threads on the smallest changed code range that owns the defect.
  Do not replace inline threads with one giant review body.
- Include the nearby code or exact symbol/endpoint/payload in the comment so the
  author can act without hunting through the review body.
- Each substantive inline thread must include:
  - The business rule, acceptance criterion, or contract being violated.
  - Root cause: what code path, state, assumption, or missing guard creates the
    problem.
  - What the code currently does.
  - A practical failure example that shows how the issue would affect users,
    data, security, operations, tests, or maintainers.
  - Validation or falsification: how the claim was checked (reproducer, type
    check, contract trace, runtime path) and what would refute it.
  - Severity and confidence (e.g. blocker/high/medium) with a one-line basis.
  - The negative impact of keeping the change as-is.
  - A concrete suggested next step (the fix direction naming the route,
    function, guard, test, migration, or config that should change).
- Link to code with a full commit SHA when creating GitHub links.
- Include a GitHub `suggestion` block when the edit is small, complete, and safe
  to apply as-is. If no complete replacement exists for the selected range,
  leave a plain inline thread with a concrete code-level recommendation or code
  sketch; never fabricate a suggestion block just to satisfy the format.
- Do not stop at business-level recommendations when the finding is code-owned.
  Add a code-level recommendation that names the route, function, component,
  payload, guard, test, migration, or config that should change.
- Use compact code snippets to explain the failure and the intended fix when it
  helps the author act quickly. Show what the current code would do versus what
  the new code would solve; use a GitHub suggestion block only when the
  replacement is complete and safe to apply as-is.
- Use `REQUEST_CHANGES` for validated blockers, `APPROVE` only when merge-ready,
  and `COMMENT` for non-blocking findings or when approval is unsafe.
- The submitted review body may contain only a short, transcript-free summary
  and links or references to inline threads. Detailed findings belong in inline
  threads. If inline review APIs fail, fall back to one submitted review body
  with file/line references and state that inline posting was unavailable.
- If no issues are found, post approval only when approval is appropriate for the
  active reviewer and policy; otherwise post a concise no-blockers comment or
  report why no public review was posted.
- Do not include validation transcripts on PR surfaces. Avoid command-by-command
  blocks such as `Validation reviewed`, `git diff --check passed`,
  `git merge-tree succeeded`, `no checks reported`, or `board unavailable`.
  Keep exact command output and board-access caveats in the operator close-out.
- Run an immediate pre-post freshness check right before submitting: re-fetch
  the current head SHA, confirm the authenticated reviewer identity that will own
  the post, re-count unresolved threads, and re-check mergeability. If the head
  SHA changed since analysis or the reviewer identity is not the one expected,
  abort the post, re-review the new head from the top, and restart. If only
  unresolved-thread count or mergeability shifted, update the verdict accordingly
  before posting.
- Before posting, run a pre-post self-check: every substantive comment is an
  inline thread on a real changed range; each has root cause, practical failure
  example, impact, and suggestion-if-applicable; no monolithic review body; no
  validation transcript; no AI attribution.

When not posting:

- Only skip posting when the user asked for draft/no-post mode, the PR is closed
  or draft, the head changed mid-review, review access is missing, auth/network is
  blocked, or approval/commenting would violate reviewer policy.
- Report the exact skip reason and the next action needed.

If the user requested response or resolution of existing comments:

- Reply to every applicable comment or review thread with the fix, evidence, or explicit reason it remains open.
- Resolve only review threads that were actually addressed.
- Re-check unresolved thread count, current checks, deployment state, and review decision after pushing.
- Request re-review when the current head no longer has a valid approval.

## Operator Close-Out Shape

This section is for the agent's response to the operator after review work. It
is not a PR surface and must not be copied into a PR review body or PR body.

```md
Findings:

1. <path>:<line>
   <business rule or contract, issue, negative impact, concrete recommendation, and code-level fix direction when applicable>

Business rules checked:

- <rule/source/result, or "Unavailable: <reason>">

Thread plan:

- <inline thread location and comment summary, or "Posted inline threads" / "Posting blocked">

Open questions:

- <question or "None">

Operator validation:

- <command, CI check, artifact, or "None provided">

Review scope:

- Sources inspected: <list>
- Instructions applied: <list>
- Posting: <posted/skipped/blocked and why>

Dropped candidates:

- <optional: why candidates were dropped when useful>

Residual risk:

- <risk or "None identified">
```
