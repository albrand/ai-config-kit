# Fleet continuation bridge

Carry existing fleet scopes through a BB/Elyra hybrid trial without changing
which project worker owns implementation. Polls read BB control-plane records,
source scope ledgers, and native Elyra provider metadata. Native card and
terminal titles report the observed state. An exited worker or imported note
cannot close a source purpose.

This is an optional helper, installed only for an explicitly requested fleet
trial. It uses Python's standard library and the installed BB, Elyra, and
native-agent-surface metadata guard. It introduces no provider login, credential store, app
replacement, permission change, or public listener.

## Operator bindings

Keep a private JSON file outside this repository. It contains:

- `schemaVersion: 1`, an absolute `stateRoot`, and a nonempty `targets` array.
- Each target's original BB `thread`, `purposes` floor, display `project`,
  native Elyra `workspace` and coordinator `node`, and absolute
  `providerJournalRoot`. IDs must come from live adapter inventories.
- Optional `workerNodes` containing source `thread`, native `node`, and `name`.
- Optional argv arrays `bbCommand` and `elyraCommand`; default to their CLIs.
- Optional absolute `bbDatabase`, `scopeRoot`, `hookStatus`, `jobsRoot`,
  `inputGuard`, and `lockFile`. Defaults use the current user's tool homes.
- `scheduler` with a unique label beginning `local.agent-config-kit.fleet.`,
  `intervalSeconds` of at least 60, and optionally an explicit CLI `path`.

Scope files are task state. They do not authenticate a caller, authorize
supersession, grant write ownership, or approve a held action. Native handles
used to synchronize titles never attest isolation for terminal/browser input.
Nudges require a fresh idle source, no outstanding descendant work, matching
verified provider route, metadata admission, and ordinary queued delivery.
After external preflight calls, one canonical adapter DB snapshot rechecks the
exclusive idle owner and the exact admitted provider/session/turn epoch before
enqueue. A changed owner or lease holds delivery. This is a delivery-time
snapshot, not an atomic remote workspace reservation or a write-owner grant;
the existing source owner and adapter remain responsible for execution fencing.
An existing state root must be owned by the current user and have no group or
other permissions (0700). A permissive root is rejected before task data is
written. Briefs and structured records use private files before writing and
atomic replacement, including when replacing an older permissive file.

## Install and exercise

```sh
python3 monitor.py --selftest
python3 test_workflow.py /absolute/private-workflow-evidence.json
python3 controller.py run --config /absolute/private-config.json --observe-only
python3 controller.py stage --config /absolute/private-config.json
```

Stage writes immutable, versioned copies and a task-scoped user LaunchAgent.
It does not activate the schedule. Before handover, prove the previous
scheduler has no active or queued run, preserve its scope/nudge state, and
share its lock file across both versions. Pause the previous schedule only
after the staged copy has completed an observation. Then activate and inspect:

```sh
python3 controller.py activate --config /absolute/private-config.json
python3 controller.py status --config /absolute/private-config.json
```

The macOS adapter polls with launchd without a model call per poll. `run` also
works on POSIX hosts with a separately owned scheduler. Actual source nudges
may cause authorized provider work; at most three attempts occur per target,
at least 30 minutes apart. All schedules and deployment operations for a target
share one advisory lock.

Each delivery intent is written before calling the source CLI. An ambiguous
result consumes the attempt budget and holds further automatic delivery, even
if the next poll loses its main state file or the spacing interval expires.
The actual adapter outcome must be reconciled; a prompt claiming success cannot
clear uncertainty. One target's delivery error leaves its siblings observable.
Staging and activation bind the complete command and working directory to the
installed artifact, including README parity, and preserve an unchanged loaded
version's activation receipt.

`monitor-state.json`, `monitor-events.jsonl`, `scheduler-last-run.json`, and
`installation.json` record actual state and artifact identity. Files are
private. Missing or corrupt source scope retains previously tracked purposes,
marks that target unknown, and leaves siblings observable. Completion requires
the original floor, observed followups, acceptance evidence, source descendants,
and native tool callbacks to be settled. Polling continues after closure to
observe later work; `finished.json` records the latest completed round.

Per-target scope baselines also survive independently of the main poll state.
Losing that state cannot turn a retained unreceipted followup into old history.
If both copies are absent after prior activity, the target remains unknown
until its baseline is reconciled. A newer uncompleted adapter request prevents
completion even when the source still appears idle. Staging alone is not prior
fleet activity: a fresh stage-first installation can record its first baseline
on its initial poll. Running the initial observation before staging remains a
useful check of operator bindings.

For queued delivery, the bridge binds the request that preceded the completed
turn. A control-plane `child-completed` notice from that thread's own child,
with a matching provider/request acceptance receipt during the turn, does not
replace the task. User input, unknown or
malformed notices, foreign children, and all requests after completion keep
delivery held. The final owner/lease check reads a consistent database snapshot
and compares the request frame before enqueueing. The notice's expected turn ID
must equal the authoritative `events.turn_id` on both start and completion;
its acceptance receipt must bind that same turn, provider session and request.

The first scope snapshot records all existing purpose IDs. Later additions
remain tracked even if added and completed between polls. Accepted revisions
newer than original closure also block completion. The source owner records
`status: "done"` and actual `evidence` on each addressed revision in its own
ledger; the bridge only reads those receipts. Older revisions already covered
by the original goals' evidenced closure do not reopen completed history.
An upgrade from a snapshot without the complete ID baseline conservatively
requires every untracked current ID. It cannot distinguish undocumented older
history from a new closed goal; its source owner reconciles evidence before
closure rather than silently discarding that uncertainty.

Evidence is a nonempty list of nonempty strings or objects with a nonempty
`note` string and an optional nonempty `at` string. An empty list is missing
acceptance; scalar values, empty notes, and malformed records are invalid.
This checks task-receipt structure, not the truth of a workflow claim. The
source owner remains responsible for persona, target, outcomes and their proof.

To remove a task-owned schedule after its bounded trial, inspect its label and
installation receipt, run `launchctl bootout gui/<uid>/<label>`, and remove only
that receipt's plist. Keep project sessions, worktrees, and journals intact.

This helper does not port BB's credential issuer, provide an Elyra SDK launch
hook, transfer provider sessions, or replace BB-only PR automation. Report
each of those outcomes separately using its actual installed runtime.
