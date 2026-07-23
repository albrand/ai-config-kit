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
  list (each entry carrying `adapter`, `adapter_status`, and candidate
  `runtime_capabilities`), and an environment-hygiene block.
- The detector executes no discovered binary. Discovery, targeting, sending,
  and trusted version verification belong to the owning adapter after its own
  trust and authorization gates.

## Reuse Before Create

Workspace duplication is a failure mode, not a feature. Before creating a
workspace, resolve the structured runtime inventory and reuse an existing one.

- The resolver (`skillsets/native-agent-surfaces/codex/native-agent-surface/scripts/resolve-workspace.py`)
  consumes a structured JSON inventory and decides `reuse | missing | ambiguous
  | unsupported` for an absolute/canonical project. It never creates and never
  executes a discovered binary.
- **Exact** cwd == project wins. A single **inside-project** cwd is eligible.
  A **broad-parent** cwd is advisory only and is **never** auto-reused.
  Ties/duplicates are **ambiguous** and fail closed.
- See `references/PROJECT_SETUP.md` (manifest-first setup),
  `references/BROWSER_E2E.md` (capability-negotiated browser E2E),
  `references/AGENT_SESSION_COORDINATION.md` (discover-before-create,
  one-writer-per-worktree cooperation), and
  `references/SESSION_START_HEALTH.md` (session-start health preflight).

## Session-Start Health

Session-start hooks load only at session start, so a stale session or an updated
hook manifest silently diverges from what is on disk. Before launch/resume, an
adapter *may* expose a **report-only** preflight (see
`references/SESSION_START_HEALTH.md`) covering: hook identity, invocation
uniqueness, runtime presence, path resolvability, and restart-required state.

The preflight is model-neutral in what it checks and never encodes a tool's
command shapes. It never repairs or mutates, never executes an arbitrary hook
command (commands are tokenized and inspected), keeps resolved targets inside
the owning plugin root, and never serializes environment values. It never claims
the in-memory process version — a stale-session advisory is computed only from
process start time vs. on-disk artifact mtime.

The Claude adapter is
`skillsets/native-agent-surfaces/codex/native-agent-surface/scripts/claude-session-hook-doctor.py`
(stdlib-only, report-only). Exit nonzero signals broken prerequisites; a restart
advisory alone may remain exit 0. Recovery is always: update via the official
command, exit, then resume the **exact** session id — never patch a cache by
hand or suppress a failure.

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

## Preference-Aware Install And Automatic Discovery

Automatic native-surface discovery is opt-in and preference-gated; it never
happens merely because the skill is present.

- The preference-aware installer
  (`skillsets/native-agent-surfaces/scripts/install.py`) copies the versioned,
  model-neutral bundle (`skillsets/native-agent-surfaces/bundle-manifest.json`)
  to `$XDG_DATA_HOME/ai-config-kit/native-agent-surfaces` and lays down a thin
  Codex adapter at `$CODEX_HOME/skills/native-agent-surface`, recording a hash
  receipt.
- Modes: `enabled` (always install), `auto` (install only on an interactive TTY
  with a supported host `cmux`|`tmux`|`zellij` present), `disabled` (persist the
  preference, install/remove nothing). An explicit `--mode` flag wins and is
  persisted; otherwise the mode is read from
  `$XDG_CONFIG_HOME/ai-config-kit/preferences.json`.
- A missing, corrupt, or unknown preference **fails closed** — it is never
  treated as consent. `disabled` skips automatic discovery entirely.
- Automatic discovery runs only when the installed preference is `enabled`, or
  `auto` has a qualifying interactive host. cmux is one adapter, never the
  universal surface; model selection / provider routing is unrelated.
- The receipt tracks bundle/adapter versions, source tree hash, per-file
  installed hashes, mode, resolved paths, and timestamp — never environment
  values. Conflicting installs are never silently overwritten: an unmanaged or
  customized target blocks unless `--backup-conflicts` backs it up. `uninstall`
  removes only receipt-owned files whose hashes still match, then persists
  `disabled`.

## Entry Point

- Doctrine: this file.
- Skillset: `skillsets/native-agent-surfaces/` (explicit-only Codex skill
  `native-agent-surface`, adapter contract, stdlib detector, reuse-first
  workspace resolver, the project-setup / browser-E2E / session-coordination /
  session-start-health references, a report-only Claude session-start hook
  doctor, the versioned `bundle-manifest.json`, and the preference-aware
  `scripts/install.py`).
