# PR Review Output Contract

Load this reference before producing final artifacts for `high-signal-pr-review` or `/code-review`.

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
| Same AI reviewer already commented          | Yes                                                     |
| Missing diff access                         | Yes                                                     |
| Missing repo instructions for changed paths | No, continue with known instructions and report the gap |

Still review AI-generated PRs when the user explicitly requests review.

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

## Business Rule Review Matrix

Before finalizing the review, build and use a compact matrix:

| Business rule / acceptance criterion | Source | Changed code | Expected behavior | Evidence |
| --- | --- | --- | --- | --- |

Use product tickets, board inventory, PR description, domain docs, backend
controllers/DTOs, API schemas, screenshots, existing tests, and current code as
sources. If a source is unavailable and the gap affects readiness, mark the
review `NEEDS DISCUSSION` or `Board regression gate blocked / NOT READY`; do not
approve based on generic code quality.

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
- Prefer inline comments on changed code. Every must-change finding needs an
  inline thread unless no changed line owns the issue.
- Start review threads on the smallest changed code range that owns the defect.
- Include the nearby code or exact symbol/endpoint/payload in the comment so the
  author can act without hunting through the review body.
- Each inline thread must include:
  - The business rule, acceptance criterion, or contract being violated.
  - What the code currently does.
  - The negative impact of keeping the change as-is.
  - A concrete suggested next step.
- Link to code with a full commit SHA when creating GitHub links.
- Include suggestion blocks when the edit is small, complete, and safe to apply
  as-is; otherwise give a concrete fix direction.
- Do not stop at business-level recommendations when the finding is code-owned.
  Add a code-level recommendation that names the route, function, component,
  payload, guard, test, migration, or config that should change.
- Use compact code snippets to explain the failure and the intended fix when it
  helps the author act quickly. Show what the current code would do versus what
  the new code would solve; use a GitHub suggestion block only when the
  replacement is complete and safe to apply as-is.
- Use `REQUEST_CHANGES` for validated blockers, `APPROVE` only when merge-ready,
  and `COMMENT` for non-blocking findings or when approval is unsafe.
- If inline review APIs fail, fall back to one submitted review body with
  file/line references and state that inline posting was unavailable.
- If no issues are found, post approval only when approval is appropriate for the
  active reviewer and policy; otherwise post a concise no-blockers comment or
  report why no public review was posted.

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

## Final Report Shape

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

Validation reviewed:

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
