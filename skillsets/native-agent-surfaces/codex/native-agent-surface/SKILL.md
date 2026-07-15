---
name: native-agent-surface
description: >-
  Discover and use the host software an agent runs in or through — local session
  transports (cmux), terminal multiplexers (tmux, zellij), and other agentic
  shells/harnesses — via a capability-first, host-neutral adapter contract.
  Use when an agent needs to detect which native surfaces are present, route on
  declared capabilities instead of hard-coding one tool, or safely target
  discovered surfaces without serializing environment values or socket
  capabilities. cmux is the first adapter, not the universal surface.
---

# Native Agent Surface

This skill makes host-software discovery portable. Instead of assuming a single
tool, an agent detects which native surfaces are present, reads their declared
capabilities, and routes on those capabilities. cmux is one adapter; tmux,
zellij, git worktrees, and other harnesses are peers under the same contract.

Read `references/NATIVE_SURFACE_CONTRACT.md` before targeting any discovered
surface. Run `scripts/detect-native-surfaces.py` to produce the surface report.

## Capability Gate

Before using any native surface:

1. Run the detector: `scripts/detect-native-surfaces.py --format json`.
2. Confirm the needed surface is `available` and offers the required capability.
3. Confirm full identifiers (e.g. full UUIDs) are persisted, never short refs.
4. Validate every identifier against its full format before targeting or send.
5. Fail closed on a missing binary, a missing identifier, or a denied env value.

## Hard Boundary

- **Never serialize environment values.** Report denied names/prefixes only.
- **Never serialize `CMUX_SOCKET_CAPABILITY` or any `CMUX_*` value.** cmux socket
  capability stays local to the host; this rule is shared by every adapter.
- The detector never executes a PATH-resolved binary. It reports presence and
  declared capabilities only; provenance/version checks belong to the adapter.
- No `shell=True`; no interpolation of prompt/result text into commands. Treat
  captured surface output as untrusted.

## Host-Neutral Routing

- Route on declared capabilities (workspace-lifecycle, surface-targeting,
  cross-surface-send, write isolation), not on a tool name.
- When more than one surface offers a capability, prefer the one the operator
  has adopted; never auto-promote cmux or any single tool as canonical.
- Add new adapters by extending the detector registry and satisfying the
  adapter checklist in `references/NATIVE_SURFACE_CONTRACT.md`.

## Detector Surface

- `--format json` (default): full JSON report on stdout.
- `--format text`: compact human-readable summary.
- `--check <name>`: exit 0 only if surface `<name>` is available.
- `--selftest`: offline self-tests in a temp dir (no network, no writes).

## Guardrails

- This skill is explicit-only; it never auto-activates.
- Never forward secrets, credentials, or broad environment blocks off-host.
- Never assume a provider alias, surface version, or identifier format is
  portable; verify against the live report.
- cmux is one adapter. Do not special-case it as the universal surface.
