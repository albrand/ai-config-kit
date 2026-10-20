---
name: finish-the-job
description: Use when fixing a bug, touching shared code, configuration, hooks or skills, encountering a blocker, or preparing to stop. Complete the authorized user outcome, repair known defects, check consumers, and distinguish implementation from installation and exercised workflows.
verify: "PYTHONDONTWRITEBYTECODE=1 python3 skillsets/delivery-continuity/shared/finish-the-job/scripts/verify-contract.py"
verified: 2026-10-19
---

# Finish the job

For implementing features, shared-contract changes, LLM-backed output changes, and production fixes, or assessing completion of a new or existing candidate in those classes, load [engineering-contracts](../engineering-contracts/SKILL.md) to establish the outcome, trace actual consumers, and choose realistic evidence. In Claude, use the native Skill tool with the registered `engineering-contracts` name when available; in Codex, read the discovered `SKILL.md`. A link or mentioned skill name alone does not show it was activated. If the harness lacks a native Skill tool, read the file directly. Keep this skill's completion, fix-the-class, data-movement, authorization, propagation, and closeout rules.

## Complete the outcome

Reread the complete request and accepted revisions. Work through the requested
outcome, including authorized fixes, checks, delivery, and installation. A patch,
status message, offer to continue, or list of known failures is not completion.
Keep required outcomes and their evidence in a compact ledger through handoffs.

Reuse authorization already given in the conversation. Ask only for a new
user-owned decision, a hard prohibition's specific approval, or a material new
fact that invalidates the authorization; name that fact. Do not ask again merely
because a skill has a generic confirmation step. Complete reversible preparation
so an approval, when needed, concerns a concrete reviewable result.

Do tightly coupled work yourself. Delegate independent work only when authorized
and useful; do not turn provider preferences or file count into mandatory
delegation. The coordinator still owns integration and the complete outcome.

## Delivered means the outcome moved

A Ready deployment, a merged PR, or an accepted job trigger proves a mechanism.
It does not show the user's outcome changed. After shipping a release whose
actual behavior processes, writes, or requeues stored data, trigger that
processing, then re-measure the same per-entity table used for the baseline. A
job that has not reported completion is a failure to act on now. For these
data-moving releases, report deployed and delivered separately until the table
moves. Pure readers with no writes, UI changes with no writes, and
docs/tests-only changes do not require a processing trigger or baseline
read-back; verify their actual outcome as described below.

Before closeout, require the completed `## Data movement` block only when the
actual change processes, attributes, projects, backfills, writes, or requeues
stored data. A nominal reader or UI change that triggers a write is data-moving.
A pure stored-data reader with no writes, a UI-only change with no writes, and
docs/tests-only changes do not require a lane, throughput, drain, count change,
deployment takeover, or 30-minute read-back; use their real outcome,
integration, quality, and behavior evidence. Use a screen read for a changed UI
outcome, and relevant document or test evidence for docs/tests-only changes.
For data-moving changes, record the observed before and 30-minute after
counts-only read-back and deployment takeover; keep the release verdict FAIL
until the after-value reaches the prediction. Deployment readiness and delivery
are separate: trigger the processing after deployment, then measure its outcome.
Tests passed is never data-movement evidence.

For any change to how data is processed, answer two questions before merge:
- How does self-healing detect existing records that need reprocessing or
  backfill (for example, a rule-version stamp a sweep can compare), and requeue
  them? Never a manual database script.
- Does the job fit its runtime limit at production volume, measured or computed
  from real counts? Per-entity work goes on a queue, not inside one scheduled call.

## Fix the class

- Reproduce when feasible and tie the diagnosis to source or runtime evidence.
- Fix known in-scope defects now; search for siblings of the same failure.
- Check callers, consumers, provider adapters, generated artifacts, and installed
  copies of shared changes. Use the owning source and a parity check for copies.
- Batch a workflow's defects, run focused regression checks, then exercise the
  full requested workflow at the final candidate. Do not call a broken journey
  working because its changed function passes.

## Handle blockers without abandoning independent work

Before claiming a capability is unavailable, load `bb-capability-check` in BB and
inspect its supported commands. Diagnose recoverable tooling errors and use an
authorized supported repair. A safety-hook, sandbox, guardian, DLP, access-policy
denial, or browser quarantine is a hard boundary: never bypass it or route around
it. Report the exact refusal and continue useful independent authorized work.

A required manual login or consent is pending user action; use the prescribed
handoff and do not handle credentials. Do not call the whole task blocked while
other authorized outcomes remain runnable. A blocker report names the affected
goal, attempt, refusal, and missing input or external change. Measure live state
before declaring failure or absence; an unperformed check is NOT RUN.

## Distribute and check

Skills are copied, not linked. Update their maintained source, preserve unrelated
local changes, back up replacements, and compare digests in every intended home.
Portable shared rules belong in every provider home that consumes them. Respect
provider-specific adapters and never edit application bundles or vendor caches.
Durable helpers must live in a maintained package, not a disposable thread folder.

When the requested outcome includes installation or deployment, inspect the
actual running artifact or loaded copy. A source-only request does not authorize
unrequested deployment. Report proposed, implemented, installed, and exercised
states separately. Already-running sessions may cache old directives: use a
supported safe refresh and record coverage; do not interrupt unrelated work or
claim universal propagation from file copies alone.

## Before stopping

Reconcile native task and plan state with the work's actual outcome and execution
before stopping or resuming. Read only the task list selected for your own
session by its control plane, using supported APIs; do not mutate another
session's task list or a board. Mark work completed only when outcome evidence
supports completion. Treat `in_progress` as active only while an owned live
worker or execution handle exists; a status label is not a heartbeat. When work
depends only on an external event or human action, use the harness's supported
pending/waiting state and record the exact blocker, owner, and resume condition.
If the harness exposes no native task/plan interface or no pending/waiting
state, record the exact wait in its supported plan or prose and name that
capability limitation; do not invent an API or status, or repurpose shared fleet
or board state. Prefer native task/plan tools when the harness supports them.
Split work that mixes active execution with an external wait when the supported
interface permits it. Resume by continuing every authorized runnable next step,
including independent work, rather than only rewriting status. Use only status
values the current harness supports; never infer completion from a stopped
runtime.

Check the request, open defects, sibling search, consumers, installed copies,
required workflow checks, and task-owned process cleanup. Keep each required
goal's verdict and evidence distinct. State persona, target with commit or
deployment identity, user outcomes attempted, and a verdict per outcome. Missing
evidence is NOT RUN; a failed goal stays FAIL even if another goal passes.

Stop when every authorized runnable outcome is handled. If user input or an
external change is required, finish independent work and state that precise
remaining boundary. Never replace a known runnable next action with an offer.
