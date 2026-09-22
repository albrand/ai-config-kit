# Agent runtime

Lessons and executable guards about running agents: the SDK calls that mislead,
the host policies that look like agent bugs, how to delegate to a
non-Anthropic provider so its cost is accountable, the traps in authoring
plugins, and the evidence gate that prevents unverified QA instructions or UI
E2E completion claims. The shared runtime also contains a fail-closed
single-flight execution lease for expensive agent work.

## `shared/` — a lesson written once

The rest of this repo uses `skillsets/<topic>/<provider>/<name>/SKILL.md`, which
forces a copy per provider and leaves near-duplicate `claude/` and `codex/`
trees to drift apart. These lessons are true of *every* agent, so they live in
`shared/` and `scripts/publish.mjs` fans each complete skill directory—including
bundled references, scripts, fixtures, and tests—out to each agent's skill
directory on each machine.

## Portability is enforced, not hoped for

Nothing here may contain a hostname, home directory, or machine name — the
repo's own rule is "remove closed-scope details". Machine-specific values are
`{{PLACEHOLDERS}}` resolved at publish time from `~/.config/agent-library/local.json`,
which is deliberately outside any repo.

Every lesson carries a `verify:` command proving its claim still holds, and a
`verified:` date. `scripts/verify.mjs` reruns them; a placeholder it cannot
resolve reports `n/a` rather than failing, because an unresolvable check says
nothing about whether the claim is true.

## `execution-ownership/` — one host owner per canonical target

`shared/execution-ownership/scripts/execution-ownership.py` provides an
atomic, stdlib-only lease keyed by repository, worktree, branch, commit, and
operation. It records protected owner metadata, supports heartbeat/release,
refuses ambiguous or malformed state, records PID/pgid and optional BB thread
metadata, and reclaims a stale lease only after the recorded owner process is
definitely gone. Its offline tests cover concurrency, lifecycle, stale
handling, malformed targets, permissions, and symlink safety.

## What does not belong here

A lesson whose content *is* closed-scope — one setup's measurements, say —
becomes a platitude once scrubbed. Those live in
`~/.config/agent-library/lessons/` instead, and the publisher picks them up
alongside these.
