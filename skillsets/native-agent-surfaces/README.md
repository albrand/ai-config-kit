# Native Agent Surfaces Skillset

This skillset makes host-software discovery **portable**. Instead of assuming a
single tool, an agent detects which native surfaces are present (local session
transports like cmux, terminal multiplexers like tmux/zellij, and other agentic
shells/harnesses), reads their declared capabilities, and routes on those
capabilities. cmux is the first adapter — not the universal surface.

Pair it with the top-level `NATIVE_AGENT_SURFACES.md` doctrine.

## Entry Points

- Codex skill: `codex/native-agent-surface/SKILL.md` (explicit-only)
- Detector CLI: `codex/native-agent-surface/scripts/detect-native-surfaces.py`
- Adapter contract: `codex/native-agent-surface/references/NATIVE_SURFACE_CONTRACT.md`

## Capability-First, Host-Neutral

- Route on declared capabilities (workspace-lifecycle, surface-targeting,
  cross-surface-send, write isolation), not on a tool name.
- The detector emits a single JSON report: schema version, timestamp, host info,
  the surface list, and an environment-hygiene block.
- Each adapter self-describes in a host-neutral registry. Add adapters there;
  do not fork the contract per tool.

## Hard Safety Boundary

- **Never serialize environment values.** Only denied names/prefixes are reported.
- **Never serialize `CMUX_SOCKET_CAPABILITY` or any `CMUX_*` value.** cmux socket
  capability stays local to the host; this rule is shared by every adapter.
- The detector never executes a PATH-resolved binary. It reports presence and
  declared capabilities only; provenance/version checks belong to the adapter.
- No `shell=True`; no interpolation of prompt/result text. Any adapter-captured
  surface output is treated as untrusted.

## Offline Validation

Run the detector self-test (fake bin dir, no network, no writes):

```sh
python3 codex/native-agent-surface/scripts/detect-native-surfaces.py --selftest
```

Emit the JSON report:

```sh
python3 codex/native-agent-surface/scripts/detect-native-surfaces.py --format json
```

Validate the Codex skill from the repo root:

```sh
node scripts/validate-codex-skills.cjs
```
