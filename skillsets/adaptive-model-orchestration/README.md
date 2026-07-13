# Adaptive Model Orchestration Skillset

Portable Codex entrypoint and optional OpenCode/GLM profile for
`ADAPTIVE_MODEL_ORCHESTRATION.md`.

## Install

Copy the whole directory below, preserving executable modes:

```text
codex/adaptive-model-orchestrator/
  -> <CODEX_HOME>/skills/adaptive-model-orchestrator/
```

Do not copy only `SKILL.md`. The skill requires its bundled references, scripts,
metadata, and optional config assets. `package-manifest.json` is the package
inventory.

For the GLM profile, copy `assets/opencode-sidecar/` to a local config directory
(for example `~/.config/opencode-sidecar`) and set
`OPENCODE_SIDECAR_CONFIG_DIR`. Review model IDs and permissions before use.
Authentication and provider membership are intentionally not packaged.

Run offline validation from the repository root:

```sh
node scripts/validate-codex-skills.cjs
```

Then run opt-in health checks:

```sh
opencode --version
opencode auth list
codex debug models --bundled
```

Use a tiny no-tool probe for each configured model/effort/agent before enabling
an always-on profile. If the skill library router is installed, refresh its
index after installation.

The bundled executor modes fail closed. They require
`OPENCODE_ALLOW_WRITES=1` and a `.ai-config-kit-sidecar-write-scope` marker at
the workdir root. Use that marker only in a dedicated isolated worktree whose
entire contents are authorized for modification. The default OpenCode agent is
read-only.

## Adoption

The portable default is `adaptive`. Operators who explicitly authorize routine
cross-family work may select `always-on-two-family`. The included GLM and
Sol/Terra/Luna mappings are a verified example profile; live catalog discovery
wins over stale names or effort labels.

## Upgrade

Replace the complete installed directory, re-run offline validation, run the
runtime probes, and refresh the skill index. Keep local credentials and provider
configuration outside the repository.
