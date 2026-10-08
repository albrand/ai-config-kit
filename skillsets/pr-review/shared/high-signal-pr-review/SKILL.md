---
name: high-signal-pr-review
description: Review pull requests or diffs with a business-rule-first, high-signal, low-false-positive workflow, mandatory PR review output contract loading, inline code threads, root-cause commentary, practical failure examples, GitHub suggestion blocks when safe, no monolithic review bodies, no validation-transcript boilerplate in PR surfaces, no AI signatures, and a board-backed regression gate. Use when the user asks an agent to review a PR, inspect a diff for merge readiness, prepare review comments, check a branch before merge, evaluate AI-generated code, improve developer-facing PR feedback, or draft PR bodies.
verify: python3 scripts/test_review_skill_source.py
verified: 2026-10-06
---

# High Signal PR Review

Use this skill for PR review, diff review, merge readiness, and public review comments.
For GitHub pull requests, treat "review" as analyze and post the review by default.
Do not split analysis from posting unless the user explicitly asks for draft/no-post mode,
the target is not a postable PR, or posting is blocked.

Before the first LLM review submission, attach both JSON and Markdown packets
from `python3 ~/.agents/skills/pr-review/scripts/pre-review.py` to `bb fleet validate --evidence` and any
advisor round; focus the LLM review on semantic gaps left by deterministic
checks. Each defect fix must add the cheapest deterministic detector that
would catch it (regex, Semgrep, lint, test, fixture, or probe), or say in one
line when only semantic review can catch it. Put generic rules in the kit starter
pack and project-specific rules in `.review-rules/`.

For every pull-request review, attempt the Hermes advisor pass (see "Hermes advisor
pass" below). It is mandatory to attempt, best-effort to obtain, and never a
publish blocker: if the advisor is unavailable, publish the independently
evidenced verdict unchanged and record the unadvised gap only in the operator
close-out. On our own PRs, a defect Hermes names blocks merge until it is fixed.
Keep Hermes, model, AI, agent, and provenance details out of every team- or
author-facing PR surface.

After the Hermes result, use the finding labels and bounded summaries to run
the Jev second-judge step below. Keep its packet local and allowlisted; do not
pass raw review text, diffs, source excerpts, secrets, or personal data.

Reviewers run on Haiku 5.5 at low reasoning (owner model policy, 2026-10-08),
where Anthropic reports that long agent prompts sometimes stop early and hand
the task back. So keep working until the review is finished: posted, or, in
draft/no-post mode or for a target that is not a postable PR, reported in
full; or blocked, with the reason stated. Don't stop after reading the diff to
report what you would check. When the review is finished, stop and report.
Don't add fixes, files or refactors to the PR that weren't asked for.

## Workflow

1. Preflight and scope the PR; load the output contract. Read `references/review-workflow.md` when you reach this step.
2. Reconstruct business intent and board-backed regression scope. Read `references/review-workflow.md` when you reach this step.
3. Review, validate findings, and prepare the review or report. Read `references/review-workflow.md` when you reach this step.
4. For an own PR, complete the Hermes review and typed-decision steps below.

## Hermes advisor pass

Every PR review attempts one. The local reviewer stays responsible for evidence, falsification, the final verdict, freshness and posting; Hermes advice never substitutes for code, ticket, board, runtime or hosted-check evidence, so verify each load-bearing claim against the exact head.

**Route.** `bb fleet validate "<claim>" --topic <name> --scope "<what was asked>" --evidence <file>...` stages the evidence on Hermes's machine, runs the review, and removes the evidence after the verdict. Send bounded evidence only:
- the claim, written as what the change does and why;
- the commits and diffstat;
- the diff, in chunks of at most about 28 KB split at file boundaries;
- the pre-review JSON and Markdown packets;
- focused test or probe output.

Never mount or register a project source on Hermes. Never send credentials, tokens, cookies, environment blocks or personal data.

Ask Hermes to challenge business-rule coverage, changed-path correctness, auth, security, data and API contracts, regression risk, validation sufficiency, and each candidate finding. Ask it to name false positives, missing evidence and overlooked defects, and for a verdict from `accept | revise | reject` with per-finding evidence; any other shape counts as no verdict. Agreement between Hermes and your own separate judgment is a confidence source; Hermes saying it is sure is not.

**Two acts, two rules.**
- **Reviewing someone else's PR:** Hermes is an advisor, mandatory to attempt and never a publish blocker.
  - If it does not answer (transport fault, capacity, timeout), post your independently evidenced verdict unchanged. Do not downgrade `REQUEST_CHANGES` to `COMMENT` or soften a finding.
  - Record `Hermes gate: BLOCKED` in the operator close-out only, and say there that the verdict is unadvised.
  - Do not claim the pass happened, and do not silently replace Hermes with another model.
  - Acknowledge queued automation work normally once the review is confirmed posted. Hermes being down is not a reason to leave an item unacknowledged; only failing to post is.
  - Skipping the attempt while Hermes is reachable leaves the review incomplete.
  - An earlier rule that made the advisor's answer a condition for posting suppressed real findings: a reviewer held back two located defects because two advisor calls timed out.
- **Merging our own PR:** Hermes reviews every one of our PRs before merge.
  - A defect it names blocks the merge until it is fixed and Hermes, on the same topic, no longer names it.
  - An objection about evidence or method that names no defect does not block.
  - When Hermes cannot be reached, fix the transport and resend rather than merging unreviewed.

**Fresh head.** Hermes advice is about the head it reviewed. Re-fetch the live head and review state just before you post, acknowledge, or merge. If the head changed after that review, discard the advice as stale and run a fresh same-topic review of the delta first. Never let advice about an older head support a post or a merge.

**Packet discipline** (measured):
- **Never put a length budget on the answer.** With the same evidence, "at most 8 lines" returned two defects where the unbounded prompt returned six, and one of the four it dropped was a race.
- **Chunk large evidence and never re-send** what the conversation already holds. One review re-sent the same payloads until it reached about a million input tokens, and its answer was discarded.
- **Continue a re-review on the same topic** (`reviewing-with-an-agent`). The same topic judges the delta against what Hermes itself examined. A fresh topic judges your summary, which is the material a biased summary can hide.
- **A transport error is not a verdict.** For example: a stale plugin handle, or a database connection that is not open.
  - Before resending, find the review thread (`bb thread list --include-hidden`, titled `Validate · ...`) and read its output with `bb thread output <id>`.
  - If it is still running, wait for it with `bb thread wait <id>`. A resend while one is in flight is refused or starts a duplicate.

**Attribution boundary.** Hermes is internal evidence. Never mention Hermes, its host, model, provider, AI assistance, agent names or review provenance on a team- or author-facing surface: inline threads, review bodies, PR comments, PR descriptions, merge-readiness comments, or ticket and chat messages to the team. Write those as direct technical feedback.

**Completion evidence**, recorded in the operator close-out:
- the exact PR and head reviewed;
- the Hermes topic and verdict, or `Hermes gate: BLOCKED`;
- which Hermes claims were confirmed, rejected or left open;
- your final verdict and posting status;
- the live-head freshness check;
- the queue acknowledgement status, when the review came from a queue.

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
- Do not post monolithic review bodies when inline review threads can be created.
- Do not copy validation transcript blocks into PR comments or PR bodies.
- When preparing or editing PR bodies, use only `Summary`, `Changes and value`,
  and `Ticket` when applicable. Keep the value section specific and
  non-repetitive, and do not add approach, validation, deployment, risk,
  follow-up, checklist, rollback, residual-risk, testing, or command-log
  sections.
- Do not add AI attribution or generated-by signatures to PR surfaces.
- Do not claim tests or CI passed unless you ran them or inspected their actual output.
- Do not approve a PR with unresolved security, data, runtime, or required-validation uncertainty.
- Do not invent product-owner, CODEOWNERS, committee, or board-role approval requirements. Under delegated tech-lead authority, decide the technical verdict from current tickets, docs, code, tests, collateral screen effects, and cross-repository contracts.
- Do not approve when missing board evidence leaves a material technical or acceptance-criteria uncertainty unresolved, or when current evidence shows a plausible protected-behavior regression. Missing board access alone is not an automatic veto when equivalent current evidence establishes the relevant behavior.

## Output

Return findings first, ordered by severity. Include:

- Findings with file and line references.
- Business rules checked, their sources, and whether the PR satisfies them.
- Open questions.
- Operator validation reviewed.
- Board checked, inventory scope/date, matched tickets, and protected behavior checked.
- Review scope and instructions applied.
- Dropped candidates when useful.
- Residual risk.

<!-- typed-decisions:begin -->
## Typed decisions here

The Hermes finding remains the candidate. Jev is an independent second judge,
not a new filter and not a merge gate.

For each Hermes finding, compare five isolated Jev judgments with Hermes'
labels: J1 finding class (`named-defect | evidence-method | unclear`); J2
dedupe (`new | duplicate | not-applicable | unclear`) and cause (`delta | pre-existing | unclear`); J3 changed-path scope (`changed | unchanged | unclear`)
and severity (`critical | high | medium | low | info | unclear`, using the
written anchors in `hermes-review-jev.py`).

Create a packet with only `review_ref`, `hermes_verdict`, `sensitive_context`,
`changed_paths`, and bounded `findings` fields (`id`, `kind`, `path`,
`severity`, `cause`, `relation`, `prior_id`, `prior_summary`, `changed_path`,
`summary`). Never send the diff, source excerpt, raw Hermes transcript, prompt,
secret, or personal data. Mark `sensitive_context` true for patient or other
personal-data reviews; the helper skips Jev. It rejects unknown packet fields,
code-like summaries, and common personal-data patterns before making a call.
The Hermes finding labels stay local to the helper for comparison; Jev receives
only the finding text, prior text, rules, and path labels.
Make `review_ref` unique to this `bb fleet validate` invocation, including the
PR, head SHA, and round identifier, so re-reviews have separate timing and
spend measurements.

Run `python3 ~/.agents/skills/typed-decisions/scripts/hermes-review-jev.py judge packet.json`.
The helper records each answer as `system-one` with a findable ref and peer
agreement. A disagreement, missing answer, or failed record is marked
`ESCALATED` for the coordinator or a Claude review. Agreement permits the
reviewer to continue considering the finding; it never blocks or unblocks merge
by itself. Keep Hermes' verdict and the coordinator's evidence-based decision
authoritative. When the workflow observes a finding's final adjudication,
resolve it immediately, including after a merge: `held` if still supported,
`overturned` if disproved. Resolve each finding separately with
`python3 ~/.agents/skills/typed-decisions/scripts/hermes-review-jev.py resolve --ref <review_ref> --finding <finding_id> --outcome held|overturned --evidence <short-outcome>`.
Do not infer that every finding was held because the PR merged.
Report the window metrics with
`python3 ~/.agents/skills/typed-decisions/scripts/decision-ledger.py review-report --days 30`.
Contract: the `typed-decisions` skill.

Record it in the decision ledger (`--point review-finding` per finding and `--point pr-verdict`), with a `--ref` a later agent can find, and resolve it when the truth arrives.
<!-- typed-decisions:end -->
