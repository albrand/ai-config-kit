---
name: native-agent-surface
description: >-
  Discover and use the host software an agent runs in or through — local session
  transports (cmux), terminal multiplexers (tmux, zellij), and other agentic
  shells/harnesses — via a capability-first, host-neutral adapter contract.
  Use when an agent needs to detect which native surfaces are present, route on
  declared capabilities instead of hard-coding one tool, reuse a project
  workspace before creating one, bootstrap a project, run browser E2E, or
  coordinate bounded multi-model sessions without serializing environment
  values or socket capabilities. cmux is the first adapter, not the universal
  surface.
---

# Native Agent Surface

This skill makes host-software discovery portable. Instead of assuming a single
tool, an agent detects which native surfaces are present, reads their declared
capabilities, and routes on those capabilities. cmux is one adapter; tmux,
zellij, git worktrees, and other harnesses are peers under the same contract.

Read `references/NATIVE_SURFACE_CONTRACT.md` before targeting any discovered
surface. Run `scripts/detect-native-surfaces.py` to produce the surface report,
and `scripts/resolve-workspace.py` to decide reuse vs. create for a project.

For project setup see `references/PROJECT_SETUP.md`, for browser E2E see
`references/BROWSER_E2E.md`, and for multi-session cooperation see
`references/AGENT_SESSION_COORDINATION.md`.

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

Each surface also reports `adapter` and `runtime_capabilities` (candidate fields
a resolver adapter can consume) plus an `adapter_status`. This is metadata only.

## Resolver Surface (reuse-first, never creates)

`scripts/resolve-workspace.py` reads a structured runtime inventory (JSON) and
decides `reuse | missing | ambiguous | unsupported` for an absolute/canonical
project path. Exact cwd == project wins; a single inside-project cwd is eligible;
a broad-parent cwd is advisory only and never reused; ties/duplicates are
ambiguous and fail closed. The resolver never executes a discovered binary.

- `--project <abs>`: canonical project path (required).
- `--surface cmux|tmux`: adapter that produced the inventory.
- `--inventory <path|->`: JSON inventory file, or `-` for stdin.
- `--selftest`: offline fixture self-tests.

## Session-Start Health

Before launch/resume, an adapter *may* run a report-only preflight that catches
stale sessions and broken session-start hook prerequisites early. The neutral
contract is `references/SESSION_START_HEALTH.md` (hook identity, invocation
uniqueness, runtime presence, path resolvability, restart-required state). It
does not encode any one tool's command shapes.

The Claude adapter is `scripts/claude-session-hook-doctor.py`: stdlib-only and
**report-only** (no repair, no mutation, no arbitrary hook execution), and
requires Claude Code `2.1.211` or newer. It:

- resolves a Claude executable from `--claude` or PATH and runs only read-only
  metadata subcommands under a bounded timeout (or takes `--plugins-json` /
  `--version-string` to avoid invoking the CLI);
- for each **enabled** plugin, reads on-disk `hooks/hooks.json`, validates
  JSON/event shape, inspects SessionStart commands, flags exact duplicate
  commands, tokenizes with `shlex` (no shell), verifies the runtime exists,
  resolves only literal path references anchored at the plugin root, and
  verifies those targets exist;
- probes active Claude processes with a best-effort `ps` and advises
  `restart_required` when a process predates an updated executable or hook
  manifest (it never claims the in-memory process version); a basename-only
  process match is downgraded to `restart_suspected` until the full native
  surface and exact session are confirmed.

```sh
scripts/claude-session-hook-doctor.py --format json            # report
scripts/claude-session-hook-doctor.py --plugins-json plugins.json
scripts/claude-session-hook-doctor.py --selftest               # offline self-test
```

Exit nonzero only for errors; a restart advisory alone stays exit 0 unless
`--strict` is given. Recovery is always: update via the official command, exit,
then resume the **exact** session id — hooks load only at session start.
Static path resolution cannot prove that a launcher injected
`CLAUDE_PLUGIN_ROOT`; a fresh launch/resume without a SessionStart failure is
the runtime proof.

## Guardrails

- This skill is explicit-only; it never auto-activates.
- Never forward secrets, credentials, or broad environment blocks off-host.
- Never assume a provider alias, surface version, or identifier format is
  portable; verify against the live report.
- cmux is one adapter. Do not special-case it as the universal surface.
