# elyra-acp

An ACP agent that bb launches as a provider (`acp-elyra-claude`, "Claude in Elyra").
bb stays the control plane: you steer from the bb thread, children are bb threads,
and bb records every turn. Each turn runs in an Elyra terminal card under the
native interactive `claude` CLI.

```
bb thread ──ACP──> elyra-acp.mjs ──elyra CLI──> Elyra card: claude --session-id/--resume
     ^                    │
     └── session/update ──┘  (tails ~/.claude/projects/**/<session>.jsonl)
```

## What it does

- **One card per Claude session.** The card title (`bb <thread id> · <title>`) is the
  address, because handles die when the app restarts. Sessions live in
  `~/.local/state/elyra-acp/sessions.json`.
- **bb identity is passed through.** `BB_THREAD_ID`, `BB_PROJECT_ID`, `BB_ENVIRONMENT_ID`,
  `BB_SERVER_URL` and `BB_CLI` come from bb's launch of the adapter, so
  `bb thread spawn --parent-self` inside Elyra creates real bb children.
- **bb's MCP tools are passed through.** bb's `bb-bridge` MCP server (AskUserQuestion,
  directory moves) goes to `claude --mcp-config`, and native AskUserQuestion is turned off.
- **bb's harness instructions go in once.** They go into `--append-system-prompt-file`
  instead of being typed on every turn (about 49K chars).
- **Pool routing.** `elyra-pool env` provides the pool route, including
  `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL`, which keeps Opus at 1M.
- **Turn end.** A turn ends on `system/stop_hook_summary`. Without that, it ends on a
  final `end_turn` followed by a quiet, idle TUI.
- **Work between bb turns.** Background-task wakeups, or anything typed straight into
  the card, are replayed at the start of the next bb turn. bb drops ACP updates that
  arrive while no prompt is open.
- **Blocking prompts are reported to bb.** Folder trust, Bypass confirmation and
  approval prompts produce a "waiting on you in Elyra card …" message.
  - Folders bb created for its own threads are trusted automatically (user decision,
    2026-10-09): `~/.bb/plugins/environment-git-worktree/host-data/worktrees/` and
    `~/.bb/thread-storage/`.
- **Stopping.** A bb stop, or adapter shutdown, sends Escape to an in-flight turn.
- **No turns typed into a shell.** A turn is typed only when Claude's footer is on
  screen. If claude exits, the card exits too.

## Imports (moving an existing Claude session under bb)

`~/.config/elyra-acp/config.json`:

```json
{
  "fallbackWorkspace": "id:<elyra workspace id>",
  "imports": {
    "cwd:/abs/env/dir": { "resumeSessionId": "<uuid>", "model": "claude-opus-5-5[1m]", "approvedBy": "user", "approvedAt": "YYYY-MM-DD" }
  }
}
```

An import is a record the user approves. The adapter never takes a resume target
from prompt text. Keys are either `<bb thread id>` or `cwd:<environment dir>`. The
directory form exists because a new thread's id isn't known until it is spawned.

## Register with bb

`bb plugin config provider-acp set customAgents '<json array>'` replaces the whole
array, so keep the existing entries:

```json
{ "id": "elyra-claude", "displayName": "Claude in Elyra",
  "command": "/abs/path/to/node", "args": ["/abs/path/to/elyra-acp.mjs"], "env": {} }
```

bb's plugin server runs with `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, so `command`
must be an absolute path.

## Limits

- Claude only. Codex children still run on bb's own `codex` provider.
- Spend made through `elyra-pool` is attributed to the pool bridge thread, not to
  each bb thread.
- When bb's system instructions change, the change applies at the next card launch.
- Logs: `~/.local/state/elyra-acp/bridge.log`. They hold env var names and bb ids,
  never values.
