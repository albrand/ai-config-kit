# cmux + Hermes Orchestration Skillset

This skillset implements bounded, default-off orchestration between **cmux**
(local UI/session transport and lifecycle surface) and **Hermes** (the provider
router, plan/delegation brain, fallback, and usage ledger on a Tailscale-only
VPS). A local deterministic broker owns the safe boundary.

Use it when an operator has adopted cmux as the local surface and Hermes as the
remote router and wants one-writer-per-task delegation, persistent master
sessions, exact per-session usage accounting, and plan arbitration with Builder.io MIT
provenance.

Pair it with `CMUX_HERMES_ORCHESTRATION.md`.

## Entry Points

- Codex orchestrator: `codex/cmux-hermes-orchestrator/SKILL.md`
- Codex plan arbiter: `codex/plan-arbiter/SKILL.md`
- Broker CLI: `codex/cmux-hermes-orchestrator/scripts/cmux-hermes.py`
- Durable work journals: `scripts/hermes-work-journal.py`
- Claude Code: `claude/commands/cmux-hermes.md` and `claude/commands/plan-arbiter.md`
- Shared references: `references/`

## Shared References

- `references/HERMES_PROTOCOL.md` — invocation rules, no `-z`, persistent master, exact usage.
- `references/CMUX_SURFACES.md` — discovery, full-UUID targeting, cross-surface send, untrusted screen output.
- `references/WORKTREE_OWNERSHIP.md` — one task/one worktree/one owner, locks, cancel/close, report-only cleanup.
- `references/HERMES_WORK_JOURNALS.md` — durable, per-task remote journals (atomic state + append-only log, no secrets, no delete).
- `references/REMOTE_AGENTS_TEMPLATE.md` — no-secrets `AGENTS.md` template for the Hermes host.
- `references/BUILDERIO_PROVENANCE.md` — Builder.io MIT source, commit hash, and adaptation policy.

## Safety Posture

- Network boundary is hard: SSH Mac → VPS only, Tailscale-only, no reverse SSH, no daemon/listener.
- The broker never forwards the full environment and never serializes `CMUX_SOCKET_CAPABILITY` or any `CMUX_*` value.
- Noninteractive advisor calls fail closed because Hermes `-q` exposes prompts in process argv. No `shell=True`, no `eval`.
- Defaults: concurrency 1, depth 1, delegation disabled, max output 1024, max turns 8, no recursion.
- Destructive cleanup defaults to report-only and needs explicit force plus clean/merged proof.
- Behavioral skills (`cmux-hermes-orchestrator`, `plan-arbiter`) are explicit-only.

## Imported Patterns

Plan arbitration, efficient-frontier handoffs, agent-watchdog verification, and
stay-within-limits budget checks adapt concepts from `BuilderIO/skills` (MIT).
See `references/BUILDERIO_PROVENANCE.md`. Concepts from the unlicensed
agent-native repository are described independently; no code or text is copied
from it.

## Offline Validation

Run the broker tests with fake cmux/ssh/git binaries (no provider contact):

```sh
python3 scripts/cmux_hermes_test.py
```

Run the durable-journal self-test in a temp dir (no network, no real root writes):

```sh
python3 scripts/hermes-work-journal.py selftest
```

Validate the Codex skills from the repo root:

```sh
node scripts/validate-codex-skills.cjs
```
