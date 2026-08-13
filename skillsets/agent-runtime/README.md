# Agent runtime

Lessons about running agents: the SDK calls that mislead, the host policies that
look like agent bugs, how to delegate to a non-Anthropic provider so its cost is
accountable, and the traps in authoring plugins.

## `shared/` — a lesson written once

The rest of this repo uses `skillsets/<topic>/<provider>/<name>/SKILL.md`, which
forces a copy per provider and leaves near-duplicate `claude/` and `codex/`
trees to drift apart. These lessons are true of *every* agent, so they live in
`shared/` and `scripts/publish.mjs` fans them out to each agent's skill
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

## What does not belong here

A lesson whose content *is* closed-scope — one setup's measurements, say —
becomes a platitude once scrubbed. Those live in
`~/.config/agent-library/lessons/` instead, and the publisher picks them up
alongside these.
