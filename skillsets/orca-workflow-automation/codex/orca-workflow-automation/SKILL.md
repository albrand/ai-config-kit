---
name: orca-workflow-automation
description: Explicit-only skill for Orca-owned workflow automation: scheduled PR-review queue sweeps, execution-productivity telemetry, and optional read-only Hermes critique. Orca owns schedules, worktree/workspace lifecycle, terminal targeting, and the browser/mobile/emulator control surface. PR review is private/draft-only by default, pinned to exact head SHA, with self-review prevention, same-reviewer+same-head+no-later-top-level-author-comment duplicate suppression, author-comment/head-change reopening, a board-backed regression gate, and no auto-merge. Use only when the user explicitly asks to run or reason about an Orca automation; never invoke implicitly.
---

# Orca Workflow Automation

This skill is **explicit-only**. Load it only when the user explicitly asks to
run, configure, or reason about an Orca-owned automation. It never runs on a
timer by itself: Orca owns scheduling and lifecycle. This skill provides the
safe operating model and the two stdlib helpers (`orca-pr-review-queue.py` and
`execution-ledger.py`) that an Orca automation invokes.

Orca is a native agent surface (worktree/workspace lifecycle, terminal
targeting, orchestration, scheduled automations, browser/mobile/emulator
control, and file-mutation ownership). See the native-agent-surfaces skillset
for capability-first discovery.

## Operating Model

- Orca owns the schedule, the fresh worktree/workspace per run, the terminal
  session, and the lifecycle. This skill is the bounded logic an Orca
  automation calls; it does not own scheduling itself.
- All guides are **dynamic and version-matched**: fetch them at runtime with
  `orca skills get <skill-name>` rather than vendoring Orca skill bodies here.
  This skill never copies Orca-owned content; it points at it.
- PR review is **private/draft-only by default**. The queue helper never posts
  reviews, never merges, and never edits a PR. Public review posting requires
  explicit policy AND active reviewer identity verification, performed outside
  this helper.
- Telemetry measures **quality and validation outcomes**, never token/speed
  rankings alone, and never records prompts, transcripts, env values, secrets,
  private branch SHAs, or repo URLs.

## Workflows

1. **PR review queue.** Read `references/PR_REVIEW_AUTOMATION.md` before any
   queue work. Use `scripts/orca-pr-review-queue.py`:
   - `scan` — fetch open PR metadata read-only via `gh`, compute eligible
     private draft work items, pin the **exact** `headRefOid`, reject/skip
     draft PRs, bots, self-authored PRs, and PRs not review-requested, and
     dedupe against XDG state by exact (PR, head, reviewer).
   - `precheck` — exit 0 only if eligible work exists; nonzero otherwise,
     without leaking which PRs exist.
   - `ack` — record a completed draft outcome for an exact PR+head+reviewer
     (and an optional latest top-level author-comment marker); a later head
     change or a later top-level author comment reopens re-review eligibility.
2. **Execution productivity ledger.** Read `references/EXECUTION_PRODUCTIVITY.md`
   before recording. Use `scripts/execution-ledger.py`:
   - `record` — append one validated JSONL row (allowlist only; unknown and
     forbidden fields rejected) to the XDG data ledger.
   - `summary` — emit aggregates only after a configurable minimum sample
     count (default 5), including elapsed median, success/validated rate, and
     retry/repair/scope-drift counts by route/skill; route recommendations only
     when the sample threshold is met.
3. **Optional Hermes critique.** Read `references/ORCA_HERMES.md`. Orca is the
   local control plane. Hermes is an optional, bounded plan critic / fallback /
   usage ledger reached through an Orca-owned persistent terminal over forward
   SSH/Tailscale only. No reverse SSH, no listeners, no environment forwarding,
   no recursive orchestration. The master thread validates every Hermes
   handoff result.

## Safe Example Orca Automation (Documentation Only)

This is an example of the *shape* of a safe Orca automation command for docs.
Do **not** create it. It is `--disabled` by default, starts a fresh session per
run, scopes to an exact repo selector, and runs a bounded precheck that leaks
no PR details:

```sh
# Example only — do not create this automation. Placeholders must be filled in.
orca automations create \
  --disabled \
  --name "draft-pr-review-queue-sweep" \
  --trigger hourly \
  --prompt "Use \\$orca-workflow-automation to produce private draft reviews only; never post, merge, or edit a PR." \
  --provider codex \
  --repo "id:<ORCA_REPO_ID>" \
  --workspace-mode new-per-run \
  --base-branch origin/main \
  --fresh-session \
  --precheck "python3 <ABSOLUTE_SKILL_PATH>/scripts/orca-pr-review-queue.py --repo <OWNER>/<REPO> precheck" \
  --precheck-timeout 30
```

`precheck` exits nonzero when there is nothing to do; an Orca automation can
gate the heavier `scan` behind a passing precheck to bound cost.

`orca automations run <id>` is a manual force-run path and may bypass the
scheduled precheck. Use a short-lived scheduled canary to validate precheck
behavior; do not use a manual run as proof that an idle schedule is cost-free.

## Hard Boundaries

- Never auto-merge. Never post a review from this skill. Never edit a PR.
- Never record prompts, transcripts, environment values, secrets, private
  branch SHAs, or repo URLs in any ledger or state file.
- Never execute an Orca automation implicitly; this skill is explicit-only.
- Orca owns lifecycle. Do not vendor Orca skill bodies; resolve them at runtime
  with `orca skills get`.
