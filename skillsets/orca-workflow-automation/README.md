# Orca Workflow Automation Skillset

Explicit-only Codex skill for **Orca-owned** workflow automation: scheduled
PR-review queue sweeps, execution-productivity telemetry, and optional read-only
Hermes critique.

This skillset does **not** schedule anything itself. Orca owns the schedule, the
fresh worktree/workspace per run, the terminal session, and the lifecycle. The
skill provides stdlib tooling to configure one repository at a time, discover
review work, record safe telemetry, and attach the optional Hermes bridge.

## Entry Points

- Codex skill: `codex/orca-workflow-automation/SKILL.md` (explicit-only)
- Codex metadata: `codex/orca-workflow-automation/agents/openai.yaml`
- Per-repo listener configurator: `codex/orca-workflow-automation/scripts/configure-orca-pr-listener.py`
- PR review queue helper: `codex/orca-workflow-automation/scripts/orca-pr-review-queue.py`
- Execution ledger helper: `codex/orca-workflow-automation/scripts/execution-ledger.py`
- Hermes terminal bridge: `codex/orca-workflow-automation/scripts/orca-hermes-terminal.py`
- Post-result workspace cleanup: `codex/orca-workflow-automation/scripts/orca-automation-workspace-cleanup.py`
- References:
  - `codex/orca-workflow-automation/references/PR_REVIEW_AUTOMATION.md`
  - `codex/orca-workflow-automation/references/EXECUTION_PRODUCTIVITY.md`
  - `codex/orca-workflow-automation/references/ORCA_HERMES.md`

## What It Does

- **Per-repo configurator** (`configure-orca-pr-listener.py`): read-only
  `plan`/`status` plus idempotent `install` for any Orca-registered GitHub
  repository. Requires explicit repo and reviewer identity, defaults disabled,
  refuses target/name collisions, and has no bulk mode.
- **PR review queue** (`orca-pr-review-queue.py`): read-only queue discovery via
  `gh` (argument arrays, never `shell=True`). Private/draft-only default, exact
  head-SHA pinning, self-review prevention, same-reviewer+same-head+no-later-
  top-level-author-comment duplicate suppression, author-comment/head-change
  reopening, and no auto-merge. Commands: `scan`, `precheck`, `ack`.
- **Execution ledger** (`execution-ledger.py`): privacy-safe append-only JSONL
  telemetry. Allowlist-only schema (unknown/forbidden fields rejected); never
  records prompts, transcripts, env values, secrets, repo URL, branch, or SHA.
  Commands: `record`, `summary` (aggregates only after a minimum sample count).
- **Post-result workspace cleanup** (`orca-automation-workspace-cleanup.py`):
  fail-closed cleanup for Orca `new-per-run` PR-review workspaces. The
  configurator's prompt runs it as the final action before private output. It
  validates the exact automation and current workspace, then spawns a detached
  watcher that removes only the matching worktree after a run with the exact
  workspaceId reaches status `completed` with a non-empty `outputSnapshot`
  (Orca has persisted the output). Blocked, partial, stale, unposted, timed-out,
  or ambiguous runs leave the workspace in place. Orca still owns lifecycle.

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

# Per-repo configurator fixtures (no real Orca or automation mutation)
python3 scripts/configure_orca_pr_listener_test.py

# Post-result cleanup fixtures (no real Orca, Popen, sleep, or worktree deletion)
python3 scripts/orca_automation_workspace_cleanup_test.py

# Byte-compile the packaged Python
python3 -m compileall codex/orca-workflow-automation/scripts
```

Validate the Codex skill from the repo root:

```sh
node scripts/validate-codex-skills.cjs
```

## Configure One Repository

Use the installed configurator for each active repository. The first install is
disabled:

```sh
python3 codex/orca-workflow-automation/scripts/configure-orca-pr-listener.py \
  --github-repo OWNER/REPO \
  --reviewer LOGIN \
  --repo-path /absolute/path/to/repo \
  plan

python3 codex/orca-workflow-automation/scripts/configure-orca-pr-listener.py \
  --github-repo OWNER/REPO \
  --reviewer LOGIN \
  --repo-path /absolute/path/to/repo \
  install
```

Run the planned precheck directly and validate a scheduled canary before
rerunning `install --enable`. `orca automations run <id>` may bypass precheck,
so it is not proof that an idle schedule is cost-free.
