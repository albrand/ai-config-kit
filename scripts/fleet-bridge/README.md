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
may cause authorized provider work; at most three are sent per target, at
least 30 minutes apart. All schedules for a target share one advisory lock.

`monitor-state.json`, `monitor-events.jsonl`, `scheduler-last-run.json`, and
`installation.json` record actual state and artifact identity. Files are
private. Missing or corrupt source scope retains previously tracked purposes,
marks that target unknown, and leaves siblings observable. Completion requires
the original floor, observed followups, acceptance evidence, source descendants,
and native tool callbacks to be settled. Polling continues after closure to
observe later work; `finished.json` records the latest completed round.

To remove a task-owned schedule after its bounded trial, inspect its label and
installation receipt, run `launchctl bootout gui/<uid>/<label>`, and remove only
that receipt's plist. Keep project sessions, worktrees, and journals intact.

This helper does not port BB's credential issuer, provide an Elyra SDK launch
hook, transfer provider sessions, or replace BB-only PR automation. Report
each of those outcomes separately using its actual installed runtime.
