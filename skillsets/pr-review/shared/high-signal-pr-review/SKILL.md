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

1. Read and obey `references/pr-review-output-contract.md` before any PR review, merge-readiness comment, posted review, or PR body. This is mandatory. If running inside a repo that vendors `agent-config-kit`, also read `skillsets/pr-review/references/pr-review-output-contract.md`, `REVIEW_AND_PR_FRAMEWORK.md`, `QUALITY_GATES.md`, and `ARCHITECTURE_AND_CODE_QUALITY.md`.
2. Preflight the PR or diff:
   - Confirm it is open and reviewable.
   - Stop or ask before continuing if it is closed, draft, obviously automated or trivial, or already reviewed by the **same authenticated reviewer at the same head**. Reviewer identity and head SHA must match exactly before reusing a prior review; a different reviewer or a different head does not count as already-reviewed.
   - Still review AI-generated PRs when the user asks for it.
   - For queue sweeps, enumerate live open PRs plus any review-required PRs and PRs whose latest non-bot comment or review-thread reply is not from the active reviewer. Treat an author reply or any head change after a review or change-request thread as a trigger to re-review the current head instead of reusing stale blocker text. Deduplicate by PR number, skip closed PRs, and record draft or access-blocked PRs instead of silently dropping them.
   - When the user has authorized merge-after-approval, merge PRs that are already approved or that this review approves only after live mergeability, required checks, unresolved conversations, branch currency, and reviewer identity constraints are verified. Do not merge self-authored PRs, draft PRs, blocked PRs, PRs with unresolved high-signal findings, or PRs whose approval/merge state cannot be verified.
   - When the user delegates review or approval on their behalf as a tech lead, treat that delegation as the active authority for the technical verdict. Do not request product-owner, CODEOWNERS-team, architecture-committee, or similar additional approval. If a current explicit repository rule or ticket names another approval, record it separately as governance or merge metadata; do not use it to avoid or replace the requested technical verdict.
   - Keep governance ownership separate from technical correctness. Review code, tickets, repository docs, tests, and contracts; do not replace a technical approve/request-changes decision with a request for a higher approval level.
3. If the task involves existing PR comments, fetch live top-level comments, reviews, review comments, review threads, head SHA, review decision, and current checks before editing or replying. Map each comment to fixed, evidence-backed reply, not applicable, or still blocked.
4. Resolve instruction scope:
   - Root instructions.
   - Path-scoped `AGENTS.md`, `CLAUDE.md`, Cursor rules, repo docs, or local review rules that cover changed files.
   - PR template and contribution docs when relevant.
5. Reconstruct business intent before judging implementation:
   - Read PR title, body, linked issue, changed-file list, and author-stated tradeoffs.
   - Extract the business rules the PR is trying to satisfy: user workflow, role/permission rules, data lifecycle, external contracts, acceptance criteria, non-goals, and previously working behavior that must remain intact.
   - Build a small review matrix: `business rule / source / changed code / expected behavior / validation evidence`. Use ticket fields, product docs, domain docs, screenshots, API contracts, backend controllers/DTOs, tests, and existing behavior as sources.
   - If the business rule or acceptance criteria are unclear and the uncertainty changes the review verdict, ask one targeted question or mark the PR **NEEDS DISCUSSION**. Do not substitute generic engineering preference for missing business intent.
   - Trace collateral behavior in the affected screen, including loading, empty, error, retry, transition, stale-data, and mutation-failure states. When behavior crosses repository boundaries, inspect the related frontend/backend PRs, DTOs, routes, schemas, and tests before judging the contract.
6. Apply **proportional** board-backed regression checking. Board access is
   mandatory only when a board is configured or linked for the repository, or
   when risk/product/release scope makes board-backed invariants material.
   - Current user and repository instructions govern the applicable board, acceptance criteria, and release requirements. Preserve those requirements without inventing a board prerequisite for unrelated local work.
   - Treat the board as evidence for ticket intent and protected behavior, not as an extra approval hierarchy. A delegated tech-lead review must not solicit separate product-owner or CODEOWNERS sign-off; record any explicit branch/release requirement separately from the technical verdict.
   - When a board applies, inventory the linked and potentially affected tickets: key, title, type, status, sprint/release, component/area,
     acceptance criteria, linked PR/release evidence, and QA/Done evidence when
     present.
   - Check the delta against current, adjacent, QA, Done, released, and
     previously working tickets that share files, routes, contracts, data,
     permissions, or user workflows with the PR.
   - Treat plausible regression of protected board-backed behavior as a Blocker
     until disproven with code evidence and targeted validation.
   - Keep **code findings distinct from board readiness**: report concrete code,
     contract, security, and data findings even when board access is missing. A
     missing or incomplete board blocks only a technical conclusion whose
     acceptance criteria or protected behavior cannot be established from the
     ticket text, repository docs, linked PRs, tests, or other current evidence.
     It does not automatically block delegated technical approval. Do not let board inventory expand re-review blocking scope
     without a causal delta path (see the delta-first re-review contract).
   - When no board is configured or linked, state that and rely on code,
     contract, and runtime evidence instead of blocking on a board that was never
     in scope.
7. Decide whether independent review passes are useful and available. If the platform permits sub-agents and runtime policy allows it, use bounded passes for instruction adherence, business-rule coverage, bug/security/logic, validation/test coverage, architecture, and board-regression mapping. The master thread filters and owns the final verdict.
   Challenge prior review comments, directives, journals, memories, cached
   conclusions, and project patterns as evidence, not authority. For
   architecture or readiness judgments, use an independent model/counterpart
   critique when available and include the authorization sentence in advisor
   briefs.
8. Review changed code against the business-rule matrix, not only local syntax. Trace changed user flows, API calls, DTOs, permissions, derived state, error paths, and persistence boundaries far enough to prove whether the PR achieves the intended business behavior. Prioritize:
   - Compile, import, type, or runtime breakage.
   - Wrong behavior in changed paths.
   - Missing or contradicted business rules, acceptance criteria, role rules, status transitions, or user-visible workflow requirements.
   - Auth, data, security, API, environment, and permission contract breaks.
   - Missing tests or misleading validation for risky changed behavior.
   - Clear scoped instruction violations.
9. Apply Matt-inspired engineering checks where relevant:
   - If intent or domain language is fuzzy, ask one targeted question or state the assumption.
   - Use domain glossary and ADRs when available.
   - Prefer behavior tests through public interfaces.
   - For bugfixes, look for a reproduced failure and regression protection.
   - For architecture changes, identify shallow modules, weak test seams, or scattered concepts only when tied to the diff.
   - Turn follow-up work into vertical-slice tickets only when ticketing is requested.
10. Validate and falsify every candidate finding before reporting. For each
    surviving finding, state its **severity** (residual impact after mitigations)
    and **confidence** (how strongly the evidence supports it). Try to falsify
    the finding first; drop it if it does not survive. Drop speculative, lint-only,
    style-only, pre-existing, unscoped, or unsupported issues.
11. For GitHub PRs, immediately before posting, refresh live PR state (current
    head SHA, reviewer identity, review threads, mergeability, and required
    checks). If the head changed, a different reviewer is active, or mergeability
    changed since analysis, recompute against the new state before posting;
    author replies and head changes trigger review, not stale output. Then prepare
    a private comment plan, dedupe findings, run the contract's pre-post
    self-check, and post only approved high-confidence review comments by default.
    Prefer one submitted PR review over loose issue comments.
    - Create an inline review thread for every must-change finding on the smallest changed code range that owns the defect. Do not collapse findings into one giant review body.
    - Each substantive thread must explain: the business rule or contract being violated, the root cause in the changed code, what the code does now, a practical failure example, the negative impact of keeping the change as-is, and a concrete next step for the developer.
    - Do not limit recommendations to business decisions. When the issue is code-owned, include the exact code-level direction needed to fix it: name the function, route, payload, guard, test, migration, or component that should change, and explain why that code change solves the failing behavior.
    - Use short code snippets when they make the fix unambiguous. Prefer snippets that contrast the bad behavior with the corrected behavior, for example: "current code sends users to `/documents` without a route; replacing it with an existing route or adding the route file prevents the 404." Keep snippets scoped and do not invent full implementations when the required business decision is still unknown.
    - Use this thread shape unless repo convention requires another format:
      `Business rule / contract: ...`
      `Issue: ...`
      `Impact: ...`
      `Suggested next step: ...`
      `Code-level recommendation: ...` when useful or when the developer would otherwise need to infer the implementation.
    - If the finding spans multiple files, thread the primary changed line and name the companion files or tests needed to complete the fix.
    - Include a GitHub suggestion block when the replacement is small, complete, and safe to apply as-is. If a suggestion block is not safe because the correct business choice is unknown or the fix spans multiple files, still provide a concrete code sketch or example alternatives that show what the bad code does versus what the proposed code would solve. Never fabricate a suggestion block.
    - If a finding needs broader context than one line can hold, keep the detailed root cause and failure example in the inline thread, and use the review body only for a short transcript-free summary that points to the thread.
    - Do not include validation transcript blocks on PR surfaces. Avoid `Validation reviewed`, command-by-command pass lists, `git diff --check passed`, `git merge-tree succeeded`, `no checks reported`, or board-access caveats in PR review comments or PR bodies. Keep exact validation evidence in the operator close-out.
    - Do not add AI attribution or signatures such as `Generated with Claude Code`, model names, AI disclaimers, or watermarks.
    - If inline review APIs fail, fall back to a single request-changes or comment review body with file and line references; report the fallback.
    - If the user explicitly asks for draft/no-post mode, report findings only and mark posting as skipped.
12. When resolving addressed review threads, reply with the fix or evidence first, resolve only those threads, then re-check review state because a new head commit can invalidate prior approval and require re-review.
13. For re-review (second or later review of the same PR, follow-up after author reply or push, or queue sweep), apply the delta-first re-review contract from `references/pr-review-output-contract.md`: record previous reviewed SHA, current SHA, `old..new` delta, prior finding ledger and dispositions, and causally affected consumers only. Raise new blockers only if introduced/materially worsened by the delta, a concrete regression caused/exposed by the delta, or an explicitly in-scope release-critical invariant with causal proof. Unrelated or pre-existing discoveries are non-blocking follow-ups. Preserve stable finding identity; do not duplicate or reopen fixed/not-applicable/accepted-risk findings without changed facts. Fall back to a full current-head review only when the baseline is unavailable, the rewritten range is unreliable, scope/security/data/architecture materially expanded, or the user asks for a fresh review.
14. If merge-after-approval is active, perform merges after the review verdicts and report each PR as merged, not merged with reason, or blocked. Prefer the repository's standard merge method and never bypass branch protection or unresolved review requirements.
15. Produce the final report using the output contract.

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
