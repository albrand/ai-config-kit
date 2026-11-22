# Archive-hold and circuit-successor procedures

## Archive hold (fleet plugin)

The following threads are never archived by fleet (orphan scan,
`orphans --retire`, member retire, orchestrator passes):

- A thread whose own or parent's ledger has an unfinished purpose.
- A review thread under a topic.

If anything else archives one, fleet restores it once and tells the
coordinator, including when the restore fails:

- The coordinator itself is never restored. A person archiving it means it:
  its ledger gets `archived_by_user_at`, and the idle guard leaves it alone.
- A child is restored at most once (`archive_restores` in the coordinator's
  ledger). Archived again after that, the archive stands; the ledger records
  `archived_again_at` and the coordinator is told.

When a child is finished, release it, so its archive stays archived:

    scope-gate.py release <coordinator> <child> --evidence "<why it is done>"

The release is recorded in the coordinator's ledger (`released_children`,
with the evidence and when). The hold, the orphan scan and the archive guard
then skip that child, and only that child; the audit line names the release.
Record it on the child's parent ledger: a release in any other ledger holds
nothing back. A child with its own ledger and unfinished purposes is still
held by that ledger. A circuit successor's releases survive the hand-back.

Every archive is appended to `~/.local/state/agent-quality/archive-audit.jsonl`.
## Circuit successor (fleet plugin)

When the fleet circuit hands a thread to a successor, the successor gets a
copy of the origin's ledger: the same purposes and revisions, plus
`inherited_from` and `inherited_at`. Its dispatches are gated the same way.
At hand-back, status changes the successor made (newer `status_marked_at`),
its evidence, new purposes and new revisions merge into the origin's ledger,
and the successor's file is kept as `<successor>.json.returned-<ms>`. When
both added a different purpose under the same id, both are kept: the
successor's is renumbered past every id and carries `renumbered_from`.
