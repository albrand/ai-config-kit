# Execution Productivity (Telemetry Ledger)

This reference defines the privacy-safe execution-productivity ledger. The
companion helper is `../scripts/execution-ledger.py` (commands `record`,
`summary`).

## Local Append-Only JSONL, XDG Data Path

Records are appended to a local JSONL file at
`$XDG_DATA_HOME/ai-config-kit/orca-workflow-automation/executions.jsonl`
(default `~/.local/share/...`). The file is created `0600` and kept restrictive;
appends are atomic and append-safe. No network, no remote sink.

## Schema (Allowlist Only)

Each row is validated against a fixed allowlist at write time. **Unknown fields
are rejected.** Allowed fields:

- `route`, `model`, `provider`, `skill`, `tool` — categorical identifiers only
  (1-128 safe characters; no whitespace or free-form text)
- `elapsed` — seconds (number)
- `validation` — `pass` | `fail` | `skipped` | `not_run`
- `retries` — non-negative int
- `repair` — non-negative int
- `outcome` — `success` | `failure` | `blocked`
- `scope_drift` — bool
- `cost` — optional number, when available

The helper adds `schema_version` and `recorded_at` (server-generated).

## Never Recorded

The ledger **never** accepts or stores:

- prompt, prompt text, messages, transcripts, history
- environment values, any `env_*` key, secrets, tokens, credentials, API keys
- repo URL / repository, branch, ref
- sha, head, commit, oid (private branch SHA / commit identity)
- diff, patch, body, content

These field names are explicitly forbidden (case-insensitive) and rejected at
write time. Defense in depth: even if an allowlist mistake occurred, the
forbidden-name check blocks them.

## Measure Quality And Validation, Not Rankings Alone

Summaries emphasize **quality and validation outcomes** (success rate, validated
rate, retry/repair/scope-drift counts) per route/skill. Token counts and raw
speed are not used as rankings; `elapsed` is reported as a median, not a
leaderboard.

## Aggregates And Minimum Sample Size

`summary` emits aggregates **only after a configurable minimum sample count**
(`--min-samples`, default 5). Below the threshold it reports `sufficient: false`
with no aggregates and no recommendations, preventing noisy conclusions from
tiny samples. Aggregates include elapsed median, success/validated rate, and
retry/repair/scope-drift counts overall and by route/skill.

## Recommendations

Routing/skill recommendations are produced **only when the sample threshold is
met** (e.g. a route with a high repair rate or low validation rate across enough
runs). They are advisory and deterministic, never automatic routing changes.
