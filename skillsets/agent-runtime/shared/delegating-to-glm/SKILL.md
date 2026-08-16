---
name: delegating-to-glm
description: >
  Use when delegating execution to GLM, opencode, or any non-Anthropic agent —
  choosing how to invoke it, or wondering why a provider you definitely used
  shows zero usage in a cost report. There are two ways to call it and only one
  of them is accountable.
verify: bb provider list --json | grep -c acp-opencode
verified: 2026-08-13
---

# Delegating to GLM so it is actually accountable

There are two ways to reach opencode/GLM, and the difference is not stylistic.

## Use the bb provider, not the subprocess

**Accountable — creates a real bb thread:**

```
bb thread spawn --provider acp-opencode --project <id> --prompt "…"
```

or, from a fleet group, `fleet_member_spawn` with `providerId: "acp-opencode"`.
The router already puts it on the top rung for `implementation`, `bulk` and
`research` work.

**Unaccountable — invisible by construction:**

```
opencode run "…" --agent build -m zai-coding-plan/glm-5.3
```

A subprocess creates no bb thread, emits no events, and can never appear in any
per-provider report. Its cost silently lands inside the *calling* agent's turn,
inflating that provider's numbers while GLM shows zero.

This is not a reporting nicety. A reviewer handed that data concluded "opencode
is unused across 18 turns, retire the directive mandating it" — confidently, and
wrongly, because the evidence it needed could not exist. **Absence from a
provider report is never evidence of non-use.**

## `--agent build`, never `--agent general`

In opencode 1.17.12 `general` is a **subagent** name, not an agent. Passing it
makes the CLI warn and silently fall back to the default agent — so the run
proceeds under something other than what you asked for, and a later timeout or
odd result is ambiguous to diagnose.

Treat `--pure`, `--variant`, `--agent` and agent names as feature-gated: probe
the installed version before depending on any of them.

## Its numbers are estimates, and say so

ACP providers report no token usage at all. bb receives only a
`contextWindowUsage` size from them, so per-turn cost is derived as
`context × round trips` and flagged `~est` in `bb fleet tokens`.

What that means when reading a report:

- Output tokens are **not counted** — nothing reports them, so nothing is claimed.
- Cache share reads 0%, because no cache figures exist. That is unknown, not bad.
- Estimated figures are **not comparable** to measured ones. Do not rank a
  measured provider against an estimated one and act on the gap.

## Setup that makes the provider exist at all

`acp-opencode` only appears if it is registered in `~/.bb/config.json` with an
**absolute** command path — bb's server runs with a minimal PATH and cannot find
a homebrew binary:

```json
{"customAcpAgents":[{"id":"opencode","displayName":"OpenCode (GLM)",
  "command":"{{OPENCODE_BIN}}","args":["acp"]}]}
```

Then `bb-app config refresh` — not `bb settings reload`.

Verify with `bb provider list`. Note it only proves bb *knows* the provider;
`hosts.providerCliStatus` is what proves a CLI is installed on a given machine,
and it does not cover ACP agents at all, so on a remote machine treat an ACP
provider as unverifiable.
