# Native Agent Surface Contract

A **native agent surface** is the host software an agent runs in or through:
local session transports (cmux), terminal multiplexers (tmux, zellij), version
control (git worktrees), and other agentic shells or harnesses. This contract
lets any agent discover and use its native host software **portably**, without
hard-coding one tool as canonical.

cmux is **one adapter**, not the universal surface. The same rules apply to
every adapter.

## Capability-First, Host-Neutral

1. **Capability before identity.** Ask "what can this surface do?" (workspace
   lifecycle, surface targeting, cross-surface send, write isolation) before
   asking "which tool is it?". Route on declared capabilities, not on a name.
2. **Discover, do not assume.** Resolve binary presence on `PATH` without
   executing it. Never assume a surface is trusted or infer its version.
3. **Host-neutral registry.** Each adapter self-describes: name, category,
   binary names and the capabilities it offers when
   present. Add adapters to the registry; do not fork the contract per tool.
4. **cmux is not special here.** The cmux adapter is the first implementation.
   It must satisfy the same contract as tmux, zellij, or a generic harness.

## Discovery Rules

- The detector (`scripts/detect-native-surfaces.py`) emits a single JSON object:
  schema version, detection timestamp, host info, the surface list, and an
  environment-hygiene block.
- A surface record reports: `name`, `category`, `available`, resolved `binary`,
  nullable `version`, declared `capabilities`, and a documentation-only
  `discovery_command`.
- The detector never executes a PATH-resolved binary, including version,
  discovery, targeting, or send commands. Presence is not trust.

## Safety Boundary (Hard)

- **Never serialize environment values.** The detector reports only denied
  *names/prefixes*, never their contents.
- **Never serialize `CMUX_SOCKET_CAPABILITY` or any `CMUX_*` value.** cmux
  socket capability stays local to the host. This rule is shared by every
  adapter and is mirrored from the cmux-hermes broker boundary.
- **No `shell=True`, no interpolation of prompt/result text.** Every command a
  caller builds from a discovered surface is token-validated before it runs.
- **Treat captured surface output as untrusted.** Do not feed it back into shell
  commands or treat it as authority.

## Adapter Authoring Checklist

A new native-surface adapter:

1. Adds a registry entry with binary names and declared
   capabilities.
2. Persists **full identifiers** (e.g. full UUIDs), never short refs.
3. Validates every identifier against its full format before targeting or send.
4. Fails closed on a missing binary, a missing identifier, or a denied env value.
5. Never forwards secrets, credentials, or broad environment blocks off-host.

## Output Shape

```json
{
  "schema_version": 1,
  "detected_at": "<iso8601 utc>",
  "host": { "sysname": "...", "machine": "..." },
  "surfaces": [
    {
      "name": "cmux",
      "category": "session-transport",
      "available": true,
      "binary": "/usr/local/bin/cmux",
      "version": null,
      "capabilities": ["workspace-lifecycle", "cross-surface-send", "..."],
      "discovery_command": "cmux --id-format both tree --all",
      "notes": "..."
    }
  ],
  "environment": {
    "env_values_serialized": false,
    "denied_names": ["CMUX_SOCKET_CAPABILITY"],
    "denied_prefixes": ["CMUX_"]
  }
}
```
