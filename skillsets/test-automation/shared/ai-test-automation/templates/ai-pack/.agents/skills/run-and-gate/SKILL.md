---
name: qa-run-and-gate
description: Compile, discover, execute, check-scenarios, judge, and wire CI for the QA kit.
---

# Run and gate

Read: `references/ci-github-actions.md` or `references/ci-azure-pipelines.md`, and `references/gate-rules.md`.

## Commands

- `node qa/bin/qa.mjs test --config qa.config.json` — compile, discover, run, emit `run-v1.json`.
- `node qa/bin/qa.mjs check-scenarios --head … --base … --file … --results …` — storage gate for scenario changes. A `DRAFT_PASSED` verdict is local diagnostics only, not a finishing result for merge.
- `node qa/bin/qa.mjs judge --scenarios … --results … --base-scenarios … [--base-results base-run-v1.json]` — verdict per scenario; nonzero on FAILED/BLOCKED.

## CI

- App PR: plan (trusted QA) → test (head, no secrets) → judge → report artifacts; publisher recomputes verdicts.
- QA repo PR: run changed scenarios and `check-scenarios` against merge base.
- Optional: upload `base-run-v1.json` from a merge-base proof run; judge blocks new scenarios that passed without the change.
