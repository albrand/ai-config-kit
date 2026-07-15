# Hermes Protocol Reference

Hermes is the remote provider router, plan/delegation brain, fallback arbiter,
and usage ledger. It runs on the Tailscale-only VPS as user `hermes` from
`/var/lib/hermes` with `HOME` and `TMUX_TMPDIR` set. Every remote command in this
skill is shaped to enforce that.

## Remote Command Shape

- SSH is Mac → VPS only (`ssh <target> -- ...`). No reverse SSH.
- The broker builds the remote argv as validated tokens joined to a fixed
  `sudo -n -u hermes env HOME=/var/lib/hermes
  TMUX_TMPDIR=/var/lib/hermes/.tmux <command>` prefix.
- No local environment is forwarded. `CMUX_SOCKET_CAPABILITY` and any `CMUX_*`
  variable are never serialized or sent.
- Noninteractive prompt submission is blocked because the current CLI exposes
  prompt content in argv. Enter prompts only through the persistent terminal.
- The broker asserts the remote login is user `hermes` before any privileged step.

## Invocation Rules

- **Never use `hermes -z`.** It auto-enables YOLO and ignores resume/worktree and
  max-turn controls. Always pass explicit controls instead.
- Noninteractive advisor calls are blocked: Hermes `chat -q` places the prompt
  in process argv. Use the persistent master terminal until a stdin-native API exists.
- Read-only advisor and peer work must stay read-only. Executor writes are
  partitioned by disjoint worktree ownership.

## Persistent Master

- A persistent Hermes master runs inside a named remote tmux session attached
  through cmux.
- The broker creates the session with `tmux new-session -d -s <name> -c
  /var/lib/hermes` if absent, or reuses it.
- **Never detach a one-shot parent while children run.** Before any detach, the
  broker inspects `tmux list-panes` for active child processes and refuses if any
  are present.
- One-shot background delegation is forbidden because children are process-bound.

## Recursive Usage

Usage is collected from exact session exports:

1. Run `hermes sessions export - --format jsonl --redact --session-id <id>`.
2. Group the row by provider/model, summing calls and token counts.
3. Query known child IDs explicitly; this Hermes version has no recursive-ledger command.

Query master and known child session IDs explicitly. Usage reads are not model calls.
