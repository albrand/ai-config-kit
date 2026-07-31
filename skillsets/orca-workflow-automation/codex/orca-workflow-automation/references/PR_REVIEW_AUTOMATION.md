# PR Review Automation (Orca-Owned)

This reference defines the operating model for the Orca-owned PR review queue.
The companion helper is
`../scripts/orca-pr-review-queue.py` (commands `scan`, `precheck`, `ack`).
Install or reconcile a listener with
`../scripts/configure-orca-pr-listener.py` (`plan`, `install`, `status`).

## Repository-Independent Installation

The configurator works for any Orca-registered GitHub repository, one explicit
target at a time. It requires the GitHub `OWNER/REPO`, reviewer login, and an
exact Orca repo path or selector. `plan` and `status` are read-only. `install`
is idempotent and disabled by default; `--enable` is an explicit promotion
after validation. Name, marker, or target mismatches fail closed. There is no
bulk activation or removal command.

## Core Model: Polling, Not Webhooks

The queue is driven by an **Orca schedule that polls**; it does not register a
GitHub webhook. Polling keeps the automation host-local, idempotent, and free of
inbound-listener exposure. An Orca automation runs `precheck` (cheap, non-leaking)
and only escalates to `scan` when eligible work exists.

## Private / Draft-Only Default

All review work produced by this queue is a **private draft**, never posted:
the helper **never posts a review, never merges, and never edits a PR**. Public
review posting requires explicit operator policy **and** active reviewer
identity verification, performed outside this helper.

## Exact Head SHA

Every work item is pinned to the precise `headRefOid` re-fetched at scan time.
Dedup and `ack` are keyed by exact **(PR number, head SHA, reviewer)**. A PR
whose head SHA is missing or cannot be pinned is rejected, never guessed.

Ack state is **repository-scoped**: the state filename is a truncated one-way
SHA-256 of the explicit `OWNER/REPO` (or the resolved cwd when `--repo` is
omitted), so two repositories never share or collide on ack state. The raw
repo/path is never stored in or printed from the state file - only the hash
appears in the filename, and records carry only PR number, head SHA, reviewer
login, and timestamps.

## Eligibility Gates (reject/skip)

A PR is eligible only when **all** hold:

- open (not closed/merged)
- not a draft PR
- author is not a bot
- not self-authored (author != active reviewer)
- the active reviewer is in `reviewRequests`
- the exact head SHA is present

## Duplicate Suppression And Reopening

- **Same reviewer + same exact head** → already reviewed; suppressed, regardless
  of author comments or any other activity.
- **Head change** (different exact SHA) → re-review eligible.

The exact head SHA is the **sole reopening signal**: a later top-level author
comment at the same head does NOT reopen re-review. Only a changed SHA does.

### Ack Semantics

`ack` is recorded once a run produces a completed, non-empty PRIVATE result for
the exact **(PR number, head SHA, reviewer)**, **including a BLOCKED outcome**.
This is what suppresses that head from being processed again. Never ack a stale
head (head changed mid-run), an interrupted run, or output-less work; those
leave the head eligible for a later retry.

## Self-Review Prevention

When `--reviewer LOGIN` is explicit, the helper pins all read-only GitHub calls
to that stored `gh` account (`gh auth token --user LOGIN`) without printing or
persisting the token. Otherwise the active reviewer login is resolved read-only
(`gh api user`). Any PR whose author equals that login is rejected as
self-authored and never enters the queue.

## Board-Backed Regression Gate

Before any review is considered complete, apply the framework's board-backed
regression gate: a plausible regression against already-working, accepted,
Done, or released behavior is a **blocker** until disproven with repo evidence.
This gate is evaluated by the reviewing agent, not by the queue helper.

## Public Posting And Identity Verification

Posting a review publicly is outside this helper. When operator policy allows
it, the posting path must (1) re-verify the active reviewer identity, (2) re-pin
the exact head SHA immediately before posting, and (3) never auto-merge.

## Never Auto-Merge

This automation has no merge capability. Merging, when explicitly authorized by
the operator, is a separate, separately-gated path that verifies mergeability,
required checks, unresolved conversations, and reviewer identity.

## Fresh Worktree Per Eligible PR

Each eligible PR is reviewed in a **fresh Orca worktree** scoped to its exact
repo selector. One writer per worktree; no cross-PR contamination.

## Post-Result Workspace Cleanup (Fail-Closed)

The configured listener prompt runs
`../scripts/orca-automation-workspace-cleanup.py watch` as its **final action**
immediately before emitting private output, armed whenever a run produces a
completed, non-empty PRIVATE result for the exact head - **including a BLOCKED
or partial report** (these still create a `new-per-run` workspace that must be
cleaned). It is NOT armed for a stale head (head changed mid-run), an
interrupted run, or output-less work. It is a bounded, fail-closed cleanup for
the `new-per-run` workspace:

- It resolves the **exact current workspace**, validates the **exact automation**
  (deterministic name + marker identity + Orca repo id), then spawns a
  **detached watcher** (argv array, `start_new_session`, cwd outside the
  workspace, DEVNULL streams; never a shell).
- The watcher polls the exact automation's runs and removes the worktree **only
  after** a run with the **exact `workspaceId`** reaches status `completed` with
  a **non-empty `outputSnapshot`** (Orca has persisted the output).
- Before removal it re-reads the exact worktree and requires **full-id equality**,
  the **same repo id**, and **`isMainWorktree` false**. It removes via
  `orca worktree rm --worktree id:<full-id> --force --json`.
- Deletion is fail-closed: blocked, partial, stale, unposted, empty, timed-out,
  or ambiguous runs (wrong automation/repo/workspace, main worktree, missing id)
  that Orca does not persist as a completed run with non-empty output
  **preserve** the workspace. Arming the watcher never deletes immediately, and
  this changes nothing about output: the review stays private/draft-only and is
  never posted, merged, or edited from here.

## Bounded Precheck

`precheck` exits 0 only if eligible work exists, and nonzero otherwise, printing
no PR details. Orca gates the heavier `scan`/review work behind a passing
precheck to bound cost and noise.

This gate applies to scheduled runs. Treat `orca automations run <id>` as a
manual force-run that may bypass precheck. Prove idle behavior with a
short-lived scheduled canary and confirm `skipped_precheck`, no workspace, and
no terminal before enabling the intended cadence.

Roll out each repo separately:

1. Run `plan` and inspect the exact target, reviewer, board policy, precheck,
   and base branch.
2. Run `install` without `--enable`.
3. Run the planned precheck directly.
4. Use a short-lived scheduled canary and verify `skipped_precheck` creates no
   workspace or terminal when idle.
5. Reconcile with `install --enable` only after the canary passes.

## Orca Owns Schedule And Lifecycle

Orca owns the schedule, the per-run fresh session, the worktree/workspace
lifecycle, and the terminal. This helper is the bounded read-only logic an Orca
automation calls; it does not own scheduling itself.
