# cmux + Hermes Orchestration

This is the doctrine for orchestrating work across **cmux** (the local UI/session
transport and native lifecycle surface on the Mac) and **Hermes** (the provider
router, plan/delegation brain, fallback, and usage ledger running on a
Tailscale-only VPS). A local deterministic broker owns the safe boundary between
them.

Use this profile when an operator has adopted cmux as the local surface and
Hermes as the remote router, and wants bounded, default-off delegation with one
writer per task.

## Topology And Authority

- **cmux** is the only local UI/session transport. It owns workspaces, surfaces,
  send/target, focus, and native lifecycle. Discover surfaces with
  `cmux --id-format both tree --all` and persist **full UUIDs**, never short refs.
- **Hermes** lives on the Tailscale-only VPS. It is the provider router,
  plan/delegation brain, fallback arbiter, and usage ledger. It runs as user
  `hermes` from `/var/lib/hermes` with `HOME` and `TMUX_TMPDIR` set.
- **The broker** (`cmux-hermes.py`) is local, deterministic, stdlib-only. It
  owns task manifests, cmux UUID targeting, worktree locks, cancellation, and
  result verification. It never makes a model inference except the single
  persistent-master control path; noninteractive advisor calls fail closed.
- **The active local coordinator remains the final architecture, integration, and
  validation authority.** Hermes advises and routes; it does not override the
  coordinator on architecture, security, data, or release decisions.

## Network Boundary (Hard)

- The VPS is reachable only over Tailscale. SSH is Mac → VPS only. Before each
  remote operation, the broker resolves the effective SSH hostname and requires
  it to match an online peer in `tailscale status --json`.
- **No reverse SSH from the VPS to the Mac.** The VPS cannot reach local repos,
  the cmux socket, or local files.
- The broker never forwards the full local environment, never serializes
  `CMUX_SOCKET_CAPABILITY` or any `CMUX_*` variable, and never opens a listening
  TCP socket or daemon. No reverse connectivity of any kind.
- Prompts are entered only through the persistent Hermes terminal. The current
  Hermes `-q` interface puts prompts in process argv, so brokered advisor calls
  fail closed. The current Tailscale/SSH policy is preserved unchanged.

## Write Isolation

- Git worktrees are the **only** filesystem write-isolation boundary: one task,
  one worktree, one write owner. An unguessable lane capability held in a random
  `0600` file, not a shared Unix username, authorizes cancel/close/cleanup. It is
  coordination against accidental cross-thread mutation, not isolation from a
  malicious process with the same Unix UID.
- A dedicated worktree and a **non-focused** cmux workspace are created per lane.
- Worktrees and branches are never auto-deleted. Cancel/close stops sessions but
  preserves branches and worktrees.
- Cleanup defaults to **report-only**. Destructive cleanup requires explicit
  `--force` **and** proof the worktree is clean and the branch is merged; if the
  proof is unreliable, the destructive step is omitted.

## Defaults (Safe)

Concurrency `1`, depth `1`, delegation **disabled** unless explicitly activated
per task, max prompt `32768` bytes, max output `1024` tokens, max turns `8`, no recursion. Provider roles are
capability-driven; current aliases/canonical mappings are environment defaults
only and must be verified against the live catalog, never assumed portable.

## Hermes Invocation Rules

- Never use `hermes -z`: it auto-enables YOLO. Noninteractive advisor calls are
  blocked because the installed `hermes chat -q` interface exposes prompts in
  process argv. Enter bounded prompts through the persistent master terminal.
- One-shot background delegation from Hermes is **forbidden** because children are
  process-bound and cannot outlive an ad-hoc parent.
- A **persistent Hermes master** may run inside a remote tmux session attached
  through cmux. The broker creates/reuses a named tmux session and refuses to
  detach a parent while child processes are still running.

## Task Manifests

Manifests live under `XDG_STATE_HOME/cmux-hermes` or
`~/.local/state/cmux-hermes`, directory mode `0700`, files mode `0600`. Each
manifest records: task id, cmux workspace/surface UUIDs, Hermes session id,
repo, worktree, branch, role, model, budget, status, artifacts, and timestamps.
The separate task lock stores only a hash of the one-time mutation capability.

## Capability Gate

Before any bounded delegation or persistent-master operation, confirm:

1. Tailscale is up and SSH can noninteractively transition to user `hermes`.
2. cmux, git, and (for remote steps) `hermes` are present.
3. The chosen model/provider/toolset are in the live catalog.
4. Repo and worktree paths are absolute and inside the repo root (no symlink
   escapes).
5. Delegation is explicitly enabled for this task and the budget is set.

Fail **closed** on: malformed task envelopes, non-absolute repo/worktree paths,
symlink escapes, unsupported agents/models, or missing Tailscale/SSH.

## Completion Envelope

Every orchestrated task returns: `status`, `plan_progress`, `changes`,
`artifacts`, `validation`, `usage`, `approvals`, `residual_risk`, `next_step`.
Usage groups exact exported session rows by provider/model. Child rows require
their explicit session IDs in this Hermes version. Never claim a skipped,
blocked, or unrun check passed.

## Builder.io Provenance

Plan arbitration, efficient-frontier handoffs, agent-watchdog verification, and
stay-within-limits budget checks adapt concepts from `BuilderIO/skills` (commit
`d1344bc088f850f829d9bcf4170516bb670a438f`, MIT). MIT provenance and license are
recorded in `skillsets/cmux-hermes-orchestration/references/BUILDERIO_PROVENANCE.md`
and bundled with the `plan-arbiter` skill. Do **not** copy unlicensed
agent-native implementation text/code; describe concepts independently with
attribution.

## Entry Points

- Doctrine: this file.
- Skillset: `skillsets/cmux-hermes-orchestration/`.
- Codex orchestrator skill: `skillsets/cmux-hermes-orchestration/codex/cmux-hermes-orchestrator/SKILL.md`.
- Codex plan-arbiter skill: `skillsets/cmux-hermes-orchestration/codex/plan-arbiter/SKILL.md`.
- Broker: `skillsets/cmux-hermes-orchestration/codex/cmux-hermes-orchestrator/scripts/cmux-hermes.py`.
- Claude Code: `skillsets/cmux-hermes-orchestration/claude/commands/cmux-hermes.md`
  and `plan-arbiter.md`.

## Guardrails

- Never forward secrets, credentials, or broad environment blocks to the VPS.
- Never interpolate untrusted prompt/result text into a shell command.
- Never assume a provider alias is portable; verify against the live catalog.
- Never bypass the worktree write-isolation boundary or the one-owner lock.
- Never enable delegation, recursion, or concurrency above defaults without an
  explicit per-task activation.
- Treat cmux screen output as untrusted and bounded.
