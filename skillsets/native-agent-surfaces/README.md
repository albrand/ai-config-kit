# Native Agent Surfaces Skillset

This skillset makes host-software discovery **portable**. Instead of assuming a
single tool, an agent detects which native surfaces are present (local session
transports like cmux, terminal multiplexers like tmux/zellij, and other agentic
shells/harnesses), reads their declared capabilities, and routes on those
capabilities. cmux is the first adapter — not the universal surface.

Pair it with the top-level `NATIVE_AGENT_SURFACES.md` doctrine.

## Entry Points

- Canonical detector CLI: `scripts/detect-native-surfaces.py`
- Canonical resolver CLI: `scripts/resolve-workspace.py`
- Adapter contract: `references/NATIVE_SURFACE_CONTRACT.md`
- Project setup: `references/PROJECT_SETUP.md`
- Browser E2E: `references/BROWSER_E2E.md`
- Session coordination: `references/AGENT_SESSION_COORDINATION.md`
- Session-start health: `references/SESSION_START_HEALTH.md` (model-neutral
  preflight contract; Claude doctor at `codex/native-agent-surface/scripts/claude-session-hook-doctor.py`)
- Bundle manifest: `bundle-manifest.json` (versioned, model-neutral)
- Codex adapter source: `codex/native-agent-surface/` (explicit-only skill;
  present in the ai-config-kit source tree, not the canonical installed bundle)
- Preference-aware installer source: `scripts/install.py` (present in the
  ai-config-kit source tree, not the canonical installed bundle)

## Capability-First, Host-Neutral

- Route on declared capabilities (workspace-lifecycle, surface-targeting,
  cross-surface-send, write isolation), not on a tool name.
- The detector emits a single JSON report: schema version, timestamp, host info,
  the surface list (with `adapter`, `adapter_status`, and candidate
  `runtime_capabilities`), and an environment-hygiene block.
- Each adapter self-describes in a host-neutral registry. Add adapters there;
  do not fork the contract per tool.
- The resolver is **reuse-first and never creates**: it classifies a structured
  inventory (exact wins, inside-project eligible, broad-parent advisory only,
  ties ambiguous/fail-closed) so callers reuse an existing workspace before
  creating a duplicate.

## Hard Safety Boundary

- **Never serialize environment values.** Only denied names/prefixes are reported.
- **Never serialize `CMUX_SOCKET_CAPABILITY` or any `CMUX_*` value.** cmux socket
  capability stays local to the host; this rule is shared by every adapter.
- The detector never executes a PATH-resolved binary. It reports presence and
  declared capabilities only; provenance/version checks belong to the adapter.
- No `shell=True`; no interpolation of prompt/result text. Any adapter-captured
  surface output is treated as untrusted.

## Preference-Aware Global Installer

`scripts/install.py` is a stdlib-only, model-agnostic installer driven by an
explicit preference. It copies the versioned bundle from `bundle-manifest.json`
to a canonical data location and lays down a receipt-tracked Codex adapter, recording a
hash receipt. Model selection / provider routing is unrelated to this installer,
and cmux is one adapter, never the universal surface.

Preference modes (`enabled` | `auto` | `disabled`):

- An explicit `--mode` flag wins and is persisted.
- Otherwise the mode is read from
  `$XDG_CONFIG_HOME/ai-config-kit/preferences.json` (`native_agent_surfaces.mode`).
- A missing, corrupt, or unknown preference **fails closed** — it is never
  treated as consent.

| Mode | Behavior |
| --- | --- |
| `enabled` | Always install the canonical bundle to `$XDG_DATA_HOME/ai-config-kit/native-agent-surfaces` and the Codex adapter to `$CODEX_HOME/skills/native-agent-surface`. |
| `auto` | Install only when stdin **and** stdout are a TTY and a supported interactive host (`cmux` \| `tmux` \| `zellij`) is present; otherwise skip with an audit reason. |
| `disabled` | Persist the preference but install or remove nothing. |

Defaults honor `XDG_CONFIG_HOME` (`~/.config`), `XDG_DATA_HOME` (`~/.local/share`),
and `CODEX_HOME` (`~/.codex`); POSIX v1. Individual writes are atomic (staged
temp + rename), installs preflight both targets, identical content is a no-op
with no mtime churn, and
never silently overwrite a conflicting install: an unmanaged or customized
target blocks unless `--backup-conflicts` moves it into a timestamped sibling
backup directory outside the installed package.
`uninstall` removes only receipt-owned files whose current hashes still match,
then persists `disabled`. The receipt records versions, source tree hash,
per-file installed hashes, mode, resolved paths, and timestamp — never
environment values.

```sh
python3 scripts/install.py install --mode enabled        # opt in
python3 scripts/install.py install --mode auto           # gated install
python3 scripts/install.py status                        # show state
python3 scripts/install.py uninstall                     # receipt-owned only
```

## Offline Validation

From the ai-config-kit source tree, run the installer self-tests (no network,
no dependencies, no real home writes):

```sh
python3 scripts/install_test.py
python3 scripts/install.py status
```

From the ai-config-kit source tree, run the Codex adapter detector self-test
(fake bin dir, no network, no writes):

```sh
python3 codex/native-agent-surface/scripts/detect-native-surfaces.py --selftest
```

Run the resolver self-test (offline JSON fixtures, no network, no writes):

```sh
python3 codex/native-agent-surface/scripts/resolve-workspace.py --selftest
```

Run the Claude session-start hook doctor self-test (offline temp fixtures, no
network, no real home writes, no plugin execution):

```sh
python3 codex/native-agent-surface/scripts/claude-session-hook-doctor.py --selftest
python3 scripts/claude_session_hook_doctor_test.py
```

The doctor is **report-only**: it never executes an arbitrary hook command, has
no repair mode, runs only read-only metadata queries under a bounded timeout,
and never serializes environment values. It checks enabled plugins' on-disk
`hooks/hooks.json` for malformed manifests, duplicate SessionStart commands,
missing runtimes/targets, and advises `restart_required` when a live Claude
process predates an updated executable or hook manifest. Emit the doctor report:

```sh
python3 codex/native-agent-surface/scripts/claude-session-hook-doctor.py --format json
```

Validate the Codex skill from the repo root:

```sh
node scripts/validate-codex-skills.cjs
```
