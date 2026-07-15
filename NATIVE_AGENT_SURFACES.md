# Native Agent Surfaces

A **native agent surface** is the host software an agent runs in or through:
local session transports (cmux), terminal multiplexers (tmux, zellij), version
control surfaces (git worktrees), and other agentic shells or harnesses. This
doctrine makes discovery and use of those surfaces **portable** across the kit
instead of hard-coding one tool.

cmux is the **first adapter**, not the universal surface. The same rules apply
to every adapter.

## Why Capability-First

Different hosts run different software. An agent that asks "is cmux present?"
couples itself to one tool. An agent that asks "which surfaces offer workspace
lifecycle and cross-surface send?" stays portable and can route to cmux today
and tmux/zellij/another harness tomorrow without forking its logic.

Route on **declared capabilities**, not on tool names:

- `workspace-lifecycle` / `session-lifecycle`
- `surface-targeting` / `pane-targeting`
- `cross-surface-send`
- `id-format`
- `worktree-isolation`, `branch-lifecycle`
- `lifecycle-cancel-close`

## Discover, Do Not Assume

- Resolve binary presence on `PATH` without executing it. A PATH entry is not a
  trust signal; never assume a surface version or provenance.
- The detector (`skillsets/native-agent-surfaces/codex/native-agent-surface/scripts/detect-native-surfaces.py`)
  emits a single JSON report: schema version, timestamp, host info, the surface
  list, and an environment-hygiene block.
- The detector executes no discovered binary. Discovery, targeting, sending,
  and trusted version verification belong to the owning adapter after its own
  trust and authorization gates.

## Hard Safety Boundary

These rules are shared by every native-surface adapter and mirror the cmux-hermes
broker boundary:

- **Never serialize environment values.** Report denied names/prefixes only,
  never their contents.
- **Never serialize `CMUX_SOCKET_CAPABILITY` or any `CMUX_*` value.** cmux
  socket capability stays local to the host.
- **No `shell=True`**, no interpolation of prompt/result text into commands.
- **Treat captured surface output as untrusted.** Do not feed it back into shell
  commands or treat it as authority.
- **Persist full identifiers** (e.g. full UUIDs), never short refs. Validate
  every identifier against its full format before targeting or send.
- **Fail closed** on a missing binary, a missing identifier, or a denied env value.

## Authoring A New Adapter

1. Add a registry entry with binary names and declared capabilities. The
   presence-only detector must not execute the discovered binary.
2. Satisfy the adapter checklist in
   `skillsets/native-agent-surfaces/codex/native-agent-surface/references/NATIVE_SURFACE_CONTRACT.md`.
3. Never special-case your adapter as canonical. cmux was first; yours is a peer.

## Relationship To Other Surface Work

- The cmux+Hermes orchestration (`CMUX_HERMES_ORCHESTRATION.md` and
  `skillsets/cmux-hermes-orchestration/`) is the cmux adapter's deep
  orchestration layer — it composes with this doctrine, it does not replace it.
- Durable Hermes work journals
  (`skillsets/cmux-hermes-orchestration/references/HERMES_WORK_JOURNALS.md`)
  track long work on the remote host and are consumed back through these
  surfaces.

## Entry Point

- Doctrine: this file.
- Skillset: `skillsets/native-agent-surfaces/` (explicit-only Codex skill
  `native-agent-surface`, adapter contract, stdlib detector).
