# Hermes Work Journals

Durable, per-task journals that live on the remote Hermes host so long-running
or interrupted work stays resumable across cmux/Hermes orchestration. Each task
gets a private directory under the configured root with an **atomic JSON state
file** and an **append-only markdown event log**.

This is the remote counterpart to the local `SESSION_JOURNALING.md` protocol:
local journals track repository work; Hermes work journals track long work that
spans the remote router/master.

## Tool

`scripts/hermes-work-journal.py` — stdlib-only, no network, no delete path.

- Root: `HERMES_WORK_JOURNAL_DIR` (default `/var/lib/hermes/work-journals`).
- Permissions: root and task directories `0700`; all files `0600`.
- Concurrency: exclusive `fcntl` flock per task.
- State: atomic writes (temp file in the task dir + `os.replace`).
- Log: append-only markdown; events are never truncated or deleted.
- Task IDs: allowlisted slug only (`^[a-z0-9][a-z0-9-]{0,63}$`).
- Secrets: common high-confidence credential signatures are refused with no
  override. This is defense in depth, not proof that arbitrary prose contains
  no secret; the operator/agent no-secrets policy remains authoritative. The
  tool never stores environment *values*.
- Bounds: each message is at most 32 KiB, each journal at most 8 MiB, and only
  the newest 256 structured checkpoints are retained in state.

## Commands

```sh
python3 scripts/hermes-work-journal.py --root <dir> <command> [options]
```

| Command | Purpose |
| --- | --- |
| `start <id>` | Create a task journal. `--message -` reads the goal from stdin. |
| `append <id>` | Append an event. `--type {action,decision,issue,result,checkpoint,close}`. |
| `heartbeat <id>` | Record liveness and optionally update `--phase` / `--next-step`. |
| `checkpoint <id>` | Record a structured resume packet with phase, next step, validation, and residual risk. |
| `resume <id>` | Reopen a paused/closed task; sets status `active`. |
| `close <id>` | Close a task. **No delete.** |
| `show <id>` | Print state JSON then the markdown journal. |
| `list` | List task journals with status and event counts. |
| `selftest` | Offline tests in a temp dir (no network, no real root writes). |

Message text comes from `--message <text>` or `--message -` (stdin).

## State Shape

```json
{
  "task_id": "feat-hermes-routing",
  "status": "active",
  "created_at": "<iso8601 utc>",
  "updated_at": "<iso8601 utc>",
  "last_heartbeat_at": "<iso8601 utc>",
  "goal": "...",
  "resume": {
    "phase": "validate",
    "next_step": "run the targeted test",
    "validation": "not_run",
    "residual_risk": ""
  },
  "checkpoints": [ { "at": "<iso8601 utc>", "note": "...", "phase": "..." } ],
  "events": 12
}
```

## Event Format

Append-only, aligned with `SESSION_JOURNALING.md`:

```md
## <iso8601 utc> - <type>

<one to three factual sentences>
```

## Safety Posture

- **No secrets.** Never paste credentials, tokens, private URLs, or
  closed-scope facts. The common-shape scanner has no override but remains a
  defense-in-depth check, not a completeness guarantee.
- **No environment values.** The tool never reads or serializes `CMUX_*` or any
  env value; only denied names/prefixes are referenced in doctrine.
- **Forward-only.** There is no delete and no truncation. To "forget" a task,
  close it; physical removal is an out-of-band operator action.
- **Offline-validation friendly.** `selftest` exercises the full lifecycle in a
  temp dir without touching `/var/lib/hermes`.

## Offline Validation

```sh
python3 scripts/hermes-work-journal.py selftest
```

## Integration

Hermes work journals are created and updated from the remote master as long work
progresses. The local orchestrator reads them back (through the cmux+Hermes
broker's read-only surfaces) to resume exactly where the remote task stopped.
They are a **fallback training/trace base, not authority** — on resume, re-open
current source files, tests, and runtime evidence before relying on a journal
conclusion.

The kit also ships `deploy/AGENTS.md`, `deploy/hermes-master-supervisor`, and
`deploy/hermes-master.service`. Install the directives as
`/var/lib/hermes/AGENTS.md` (owner `hermes`, mode `0600`), the supervisor as
`/usr/local/libexec/hermes-master-supervisor` (owner `root`, mode `0755`), and
the unit as `/etc/systemd/system/hermes-master.service` (owner `root`, mode
`0644`). Create `/var/lib/hermes/.tmux` as `hermes:hermes` mode `0700`, then run
`systemctl daemon-reload && systemctl enable --now hermes-master.service`. The
journal is disk-backed and survives both SSH disconnects and reboots.
