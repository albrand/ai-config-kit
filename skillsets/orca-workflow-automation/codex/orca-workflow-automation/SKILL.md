---
name: orca-workflow-automation
description: >-
  Explicit-only skill for Orca-owned workflow automation, including
  per-repository PR listeners, scheduled review-queue sweeps,
  execution-productivity telemetry, and optional read-only Hermes critique.
  Orca owns schedules, worktree/workspace lifecycle, terminal targeting, and
  browser/mobile/emulator control. Review work is private/draft-only by
  default, pinned to an exact head SHA, board-gated, duplicate-suppressed, and
  never auto-merged. Use only when the user explicitly asks to run, configure,
  or reason about an Orca automation; never invoke implicitly.
---

# Orca Workflow Automation

This skill is **explicit-only**. Load it only when the user explicitly asks to
run, configure, or reason about an Orca-owned automation. It never runs on a
timer by itself: Orca owns scheduling and lifecycle. This skill provides the
safe operating model and stdlib tools for per-repository listener
configuration, queue discovery, telemetry, and the optional Hermes bridge.

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

1. **Per-repository listener configuration.** Use
   `scripts/configure-orca-pr-listener.py` for any Orca-registered GitHub
   repository. Require an explicit `OWNER/REPO`, reviewer, and Orca repo path
   or selector. Run `plan`, then `install` without `--enable`; validate the
   direct precheck and a scheduled canary before reconciling with `--enable`.
   The configurator is idempotent, refuses identity/name collisions, and never
   performs bulk activation.
2. **PR review queue.** Read `references/PR_REVIEW_AUTOMATION.md` before any
   queue work. Use `scripts/orca-pr-review-queue.py`:
   - `scan` — fetch open PR metadata read-only via `gh`, compute eligible
      private draft work items, pin the **exact** `headRefOid`, reject/skip
      draft PRs, bots, self-authored PRs, and PRs not review-requested, and
      dedupe against **repository-scoped** XDG state (filename is a one-way hash
      of OWNER/REPO, or the cwd when `--repo` is omitted; the raw repo/path is
      never stored) by exact (PR, head, reviewer). An explicit `--reviewer`
      pins read-only GitHub calls to that stored `gh` account without exposing
      its token.
   - `precheck` — exit 0 only if eligible work exists; nonzero otherwise,
     without leaking which PRs exist.
   - `ack` — record a completed draft outcome for an exact PR+head+reviewer,
      once a run produces a completed, non-empty PRIVATE result (including a
      BLOCKED outcome). The exact head SHA is the sole reopening signal: a same
      head never reopens after author comments or any other activity; only a
      changed SHA is eligible again. Never ack a stale head, an interrupted run,
      or output-less work.
3. **Execution productivity ledger.** Read `references/EXECUTION_PRODUCTIVITY.md`
   before recording. Use `scripts/execution-ledger.py`:
   - `record` — append one validated JSONL row (allowlist only; unknown and
     forbidden fields rejected) to the XDG data ledger.
   - `summary` — emit aggregates only after a configurable minimum sample
     count (default 5), including elapsed median, success/validated rate, and
     retry/repair/scope-drift counts by route/skill; route recommendations only
     when the sample threshold is met.
4. **Optional Hermes critique.** Read `references/ORCA_HERMES.md`. Orca is the
   local control plane. Hermes is an optional, bounded plan critic / fallback /
   usage ledger reached through an Orca-owned persistent terminal over forward
   SSH/Tailscale only. No reverse SSH, no listeners, no environment forwarding,
   no recursive orchestration. The master thread validates every Hermes
   handoff result. Use `scripts/orca-hermes-terminal.py --name
   orca-hermes-master` as the terminal command; it validates variable tokens,
   clears SSH environment forwarding, and never invokes a local shell.
5. **Post-result workspace cleanup.** The configured listener prompt runs
   `scripts/orca-automation-workspace-cleanup.py watch` as its FINAL action
   before emitting private output, armed whenever a run produces a completed,
   non-empty PRIVATE result for the exact head - including a BLOCKED or partial
   report (these still create a workspace that must be cleaned). It is NOT armed
   for a stale head, an interrupted run, or output-less work. It validates the
   exact automation (name + marker identity + repo id) and the current
   new-per-run workspace, then spawns a detached watcher that removes ONLY the
   matching worktree after a run with the exact `workspaceId` reaches status
   `completed` with a non-empty `outputSnapshot` (Orca has persisted the
   output). It is fail-closed: before removal it re-reads the exact worktree and
   requires full-id equality, the same repo id, and `isMainWorktree` false.
   Blocked, partial, stale, unposted, empty, timed-out, or ambiguous runs that
   Orca does not persist as a completed run with non-empty output preserve the
   workspace; arming the watcher never deletes immediately. Orca still owns the
   schedule and lifecycle.

## Install One Disabled Listener

The configurator works for any Orca-registered GitHub repository. It creates
only the repository explicitly named and defaults to disabled:

```sh
python3 scripts/configure-orca-pr-listener.py \
  --github-repo OWNER/REPO \
  --reviewer LOGIN \
  --repo-path /absolute/path/to/repo \
  plan

python3 scripts/configure-orca-pr-listener.py \
  --github-repo OWNER/REPO \
  --reviewer LOGIN \
  --repo-path /absolute/path/to/repo \
  install
```

Run the emitted precheck directly, then prove the scheduled `skipped_precheck`
path creates no workspace or terminal. Only then rerun `install --enable`.

`orca automations run <id>` is a manual force-run path and may bypass the
scheduled precheck. Use a short-lived scheduled canary to validate precheck
behavior; do not use a manual run as proof that an idle schedule is cost-free.

## Hard Boundaries

- Never auto-merge. Never post a review from this skill. Never edit a PR.
- Never record prompts, transcripts, environment values, secrets, private
  branch SHAs, or repo URLs in any ledger or state file.
- Never execute an Orca automation implicitly; this skill is explicit-only.
- Never bulk-enable listeners. Install and validate each target repository
  separately.
- Orca owns lifecycle. Do not vendor Orca skill bodies; resolve them at runtime
  with `orca skills get`.
