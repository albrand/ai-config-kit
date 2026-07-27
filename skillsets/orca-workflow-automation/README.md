# Orca Workflow Automation Skillset

Explicit-only Codex skill for **Orca-owned** workflow automation: scheduled
PR-review queue sweeps, execution-productivity telemetry, and optional read-only
Hermes critique.

This skillset does **not** schedule anything itself. Orca owns the schedule, the
fresh worktree/workspace per run, the terminal session, and the lifecycle. The
skill provides the safe operating model and two stdlib helpers that an Orca
automation invokes.

## Entry Points

- Codex skill: `codex/orca-workflow-automation/SKILL.md` (explicit-only)
- Codex metadata: `codex/orca-workflow-automation/agents/openai.yaml`
- PR review queue helper: `codex/orca-workflow-automation/scripts/orca-pr-review-queue.py`
- Execution ledger helper: `codex/orca-workflow-automation/scripts/execution-ledger.py`
- Hermes terminal bridge: `codex/orca-workflow-automation/scripts/orca-hermes-terminal.py`
- References:
  - `codex/orca-workflow-automation/references/PR_REVIEW_AUTOMATION.md`
  - `codex/orca-workflow-automation/references/EXECUTION_PRODUCTIVITY.md`
  - `codex/orca-workflow-automation/references/ORCA_HERMES.md`

## What It Does

- **PR review queue** (`orca-pr-review-queue.py`): read-only queue discovery via
  `gh` (argument arrays, never `shell=True`). Private/draft-only default, exact
  head-SHA pinning, self-review prevention, same-reviewer+same-head+no-later-
  top-level-author-comment duplicate suppression, author-comment/head-change
  reopening, and no auto-merge. Commands: `scan`, `precheck`, `ack`.
- **Execution ledger** (`execution-ledger.py`): privacy-safe append-only JSONL
  telemetry. Allowlist-only schema (unknown/forbidden fields rejected); never
  records prompts, transcripts, env values, secrets, repo URL, branch, or SHA.
  Commands: `record`, `summary` (aggregates only after a minimum sample count).

## Hard Boundaries

- Never auto-merge. Never post a review from this skill. Never edit a PR.
- Never record prompts, transcripts, environment values, secrets, private branch
  SHAs, or repo URLs.
- Never execute an Orca automation implicitly; this skill is explicit-only.
- Do not vendor Orca skill bodies; resolve them at runtime with
  `orca skills get <name>`.

## Offline Validation

```sh
# PR review queue business logic (fixtures, no gh, no real home writes)
python3 scripts/orca_pr_review_queue_test.py

# Execution ledger (fixtures, no real home writes)
python3 scripts/execution_ledger_test.py

# Forward-SSH bridge argv contract (offline; no connection)
python3 scripts/orca_hermes_terminal_test.py

# Byte-compile the packaged Python
python3 -m compileall codex/orca-workflow-automation/scripts
```

Validate the Codex skill from the repo root:

```sh
node scripts/validate-codex-skills.cjs
```

## Safe Example Orca Automation (Documentation Only)

This is the *shape* of a safe command for docs. Do **not** create it. It is
`--disabled` by default, starts a fresh session per run, scopes to an exact repo
selector, and runs a bounded, non-leaking precheck:

```sh
# Example only — do not create this automation. Placeholders must be filled in.
orca automations create \
  --disabled \
  --name "draft-pr-review-queue-sweep" \
  --trigger hourly \
  --prompt "Use \\$orca-workflow-automation to produce private draft reviews only; never post, merge, or edit a PR." \
  --provider codex \
  --repo "id:<ORCA_REPO_ID>" \
  --workspace-mode new-per-run \
  --base-branch origin/main \
  --fresh-session \
  --precheck "python3 <ABSOLUTE_SKILL_PATH>/scripts/orca-pr-review-queue.py --repo <OWNER>/<REPO> precheck" \
  --precheck-timeout 30
```

`orca automations run <id>` may force a run without applying the scheduled
precheck. Validate the precheck with a short-lived scheduled canary, then
restore the intended cadence.
