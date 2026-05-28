# PR Review Output Contract

Load this reference before producing final artifacts for `high-signal-pr-review` or `/code-review`.

## Source Evidence

Record:

- PR identifier or diff source.
- PR title, description, linked issue, and author intent.
- Changed file list.
- Applicable instruction files and their scope.
- Validation output inspected.
- External systems used or unavailable.
- Whether comment mode was requested.

## Preflight

Before reviewing, decide whether to continue:

| Check | Stop Unless User Overrides |
| --- | --- |
| PR closed | Yes |
| PR draft | Yes |
| Obviously automated or trivial | Yes |
| Same AI reviewer already commented | Yes |
| Missing diff access | Yes |
| Missing repo instructions for changed paths | No, continue with known instructions and report the gap |

Still review AI-generated PRs when the user explicitly requests review.

## Review Passes

Use the strongest practical version supported by the active tool:

1. Intent pass: title, body, linked issue, changed-file list.
2. Instruction pass: root and path-scoped instructions that apply to changed files.
3. Bug and contract pass: changed code only, with surrounding context as needed.
4. Security and data pass: auth, permissions, isolation, input/output, secrets, logging.
5. Test and validation pass: behavior coverage and evidence quality.
6. Architecture pass: boundaries, domain language, ADR conflicts, deep-module opportunities.

When sub-agents are available and approved by runtime policy, use independent bounded passes. Keep the master thread responsible for filtering and final judgment.

## High-Signal Finding Bar

Report only findings that meet at least one condition:

- The changed code will fail to compile, parse, import, or resolve.
- The changed path will definitely produce wrong behavior.
- The change breaks an auth, data, security, runtime, API, or environment contract.
- The change violates an applicable scoped instruction and the exact rule can be cited.
- Required validation is missing for a risky behavior introduced by the PR.

Drop:

- Style-only concerns.
- Lint-only concerns unless repo policy makes them blocking.
- Speculative future issues.
- Pre-existing issues unless the PR makes them materially worse.
- General quality suggestions not tied to changed behavior.
- Findings that require unsupported assumptions.

## Matt-Inspired Review Additions

Use these additions only when relevant to the changed surface:

- If the PR intent is ambiguous, ask one targeted question or state the assumption before reviewing.
- Use the repo's domain glossary, `CONTEXT.md`, `CONTEXT-MAP.md`, and ADRs when present.
- Prefer tests that verify observable behavior through public interfaces.
- For bugfix PRs, check whether the original failure was reproduced and locked with a regression test or equivalent feedback loop.
- Look for shallow pass-through modules, scattered domain concepts, or weak test seams when the PR touches architecture.
- Convert follow-up work into vertical-slice tickets, not horizontal chores, when ticketing is requested.

## Comment Mode

Default: report findings in the terminal or final response only.

If the user requested comments:

- Prepare a private comment plan first.
- Post at most one comment per unique issue.
- Prefer inline comments on changed code.
- Link to code with a full commit SHA when creating GitHub links.
- Include suggestion blocks only for small fixes that fully resolve the issue.
- If no issues are found and a summary comment is requested, post a short no-issues summary.

## Final Report Shape

```md
Findings:
1. <path>:<line>
<issue, impact, and concrete recommendation>

Open questions:
- <question or "None">

Validation reviewed:
- <command, CI check, artifact, or "None provided">

Review scope:
- Sources inspected: <list>
- Instructions applied: <list>
- Comment mode: <yes/no>

Dropped candidates:
- <optional: why candidates were dropped when useful>

Residual risk:
- <risk or "None identified">
```
