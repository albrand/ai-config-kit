# Adaptive Model Orchestration Skillset

Portable Codex entrypoint for the Codex/Claude routing policy in
`ADAPTIVE_MODEL_ORCHESTRATION.md`. The bundled GLM provider profile has been
retired and is not installed or included. Hermes's current review route stays
working until Codex (model set in Hermes's own config) is verified there.

## Install

Copy the whole directory below, preserving executable modes:

```text
codex/adaptive-model-orchestrator/
  -> <CODEX_HOME>/skills/adaptive-model-orchestrator/
```

Do not copy only `SKILL.md`. The skill requires its bundled references, scripts,
metadata, and optional config assets. `package-manifest.json` is the package
inventory.

No provider credentials, authentication, model IDs, or OpenCode configuration
are packaged. Resolve the live Codex route and Claude availability from the
operator's environment. OpenCode is legacy and opt-in only; never select GLM.

Run offline validation from the repository root:

```sh
node scripts/validate-codex-skills.cjs
```

Then run opt-in route checks:

Use the live fleet route for the exact Codex provider, model, and reasoning
level. Keep architecture, security, authentication, data-loss, release, and
final-review work on Claude. After verification, Hermes PR reviews use Codex
(model set in Hermes's own config) through `bb fleet validate`; preserve the
current working route until then.

Any explicitly requested legacy OpenCode executor mode must fail closed and
use its dedicated isolated worktree and explicit write gate. The default route
does not invoke OpenCode.

## Adoption

The portable default is the Codex/Claude route described above. Live catalog
discovery wins over stale model names and effort labels. This profile does not
support GLM for ordinary execution; Hermes's independently configured review
route remains working through its verified replacement.

## Upgrade

Replace the complete installed directory, re-run offline validation, then run
the repository router's `--check` against the candidate skill library. Keep
local credentials and provider configuration outside the repository.
