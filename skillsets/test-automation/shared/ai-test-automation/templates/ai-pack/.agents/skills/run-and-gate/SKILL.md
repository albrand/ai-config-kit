---
name: qa-run-and-gate
description: Compile, discover, execute, check-scenarios, judge, and wire CI for the QA kit.
---

# Run and gate

Read: `references/ci-github-actions.md` or `references/ci-azure-pipelines.md`, and `references/gate-rules.md`.

## Commands

- `node qa/bin/qa.mjs test --config qa.config.json` — compile, discover, run, emit `run-v1.json`.
- `node qa/bin/qa.mjs check-scenarios --head … --base … --file … --results …` — storage gate for scenario changes.
- `node qa/bin/qa.mjs judge --scenarios … --results … --base-scenarios … --base-results base-run-v1.json` — verdict per scenario; nonzero on FAILED/BLOCKED. Pass `--base-results` for every new scenario.

- `node qa/bin/qa.mjs canary` — runs the gate canaries alone; `judge` and `check-scenarios` run them first and stop with `SANITY_CANARY_FAILED` when a known-bad input is no longer rejected. Fix the gate, never the canary.
- `node qa/bin/qa.mjs test --env <name> --base-url <url>` — against a deployed target. Refused with `TARGET_NOT_ALLOWED` unless the origin is in `environments.<name>.origins`; `CREDENTIALS_NOT_FROM_CI` unless identities come from the declared CI variables and avoid the deny list; `PREFLIGHT_BLOCKED` (exit 2, report **BLOCKED**, never pass or fail) when a prerequisite is missing; `CLEANUP_UNVERIFIED` (exit 1) when a record the run created is not proven gone. Never print a secret.
- `check-scenarios --source` counts a scenario as bound only when a runnable test title or `scenario_id` label carries its ID; a comment, a string or a skipped test does not.

## Finishing (AI work vs merge)

- Never approve your own scenario; keep the binding `draft` until QA approves it.
- AI sequence: plan → run tests → gate (`check-scenarios` / `judge`). With a draft binding the gate ends in `DRAFT_PASSED`: tests ran and passed and no blocking finding is open (exit 3 without `--allow-draft-pass`).
- `--allow-draft-pass` only turns that exit code into 0 so a local command chain can complete; it does not waive blocking findings or change verdict meaning. It is never a finish line.
- AI work is finished when the gate reports `DRAFT_PASSED` with no blocking finding and the scenario is handed to QA for approval. Report **tests pass, awaiting QA approval** — never passed, verified, or done.
- Merge verdict: run the gate **without** `--allow-draft-pass` after QA sets the binding to `ready`. A draft pass is never a merge verdict.
- Fix every blocking finding (unasserted expected line, visual value not asserted, test that cannot fail, mock write that no scenario declares) before hand-off; the flag does not excuse it.
- A red test that reveals an unfixed product bug is the gate working: file the bug (`bug-report` skill) and keep the test red. Never add `skip`, `fixme`, `test.fail`, a retry or a longer timeout to get a green run.
- Report the missing evidence by name. A visual check without its wrong-value red run, or a new scenario without a merge-base run, is **NOT RUN**, not passed.

## CI

- App PR: plan (trusted QA) → test (head, no secrets) → judge → report artifacts; publisher recomputes verdicts.
- QA repo PR: run changed scenarios and `check-scenarios` against merge base.
- Merge-base proof: the CI templates run a `base-proof` job whenever a scenario is new or changed (same scenarios on the real merge base from `qa.mjs merge-base`, not the target tip; results in `base-run-v1.json`, commit in `base-meta.json` as `baseSha`), and `judge` takes `--base-results` unconditionally in that case. A missing base results file, or a `baseSha` that is not the merge base `judge` resolves, fails the job with `NOT RUN`. `judge` blocks new scenarios that passed without the change. Do not make the flag conditional on the file existing.
