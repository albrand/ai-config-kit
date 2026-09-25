# qa-enforcement skillset

Fail-closed QA ship gate + discovery-first QA sweep skill, built 2026-09-24
from the qa-speed-quality research report §2 (report at
~/.bb/thread-storage/qa-speed-quality-research-20260924/report.md).

## What it is

- `shared/qa-sweep/` — the `qa-sweep` skill (P0 scope, P1 walk+inventory, P2
  cluster with red repro, P3 one plan, P4 fix per cluster, P5 re-walk, P6
  ship) plus `scripts/ship-gate.py` (the gate: `hook`, `stop`, `check`,
  `clusters`, `record`, `selftest`) and templates (git pre-push, GitHub
  Actions job, .qa/config example).
- `hooks/` — host wiring: `qa-ship-gate-hook.sh` (PreToolUse),
  `qa-stop-hook.sh` (Stop), the extended `coordinator-hook-pretool.sh`, and
  `install.sh`.

## How it enforces

A repo opts in by committing `.qa/config.json`; from then the gate is ALWAYS
ON for that repo (no flag, no off switch short of removing the opt-in — that
is the design). Ship commands — v2: merges (`gh pr merge`/`gh pr ready`), pushes to protected
refs (default branch + `protected_branches`; refspec, `HEAD:dev`, upstream,
`--all`/`--mirror`), production deploys (`--prod`/promote/fly), plus
repo-configured regexes — are denied unless: every inventory row closed or fail-escalated with a
reference, every row clustered, every cluster's repro failed once, every
cluster in plan.md, re-walk at the exact SHA being shipped all-PASS,
qa-e2e-gate green on the evidence packet, and the configured deployed-SHA
check green. Non-ship commands and non-opted-in repos are never touched;
crashes allow except on ship commands in opted-in repos (fail closed).

Layers: host PreToolUse (Claude Code + Codex via coordinator-hook-pretool.sh,
which keeps its coordinator block unchanged), git pre-push template, CI
required-check template (the unforgeable layer; agents self-attest the .qa
files), and a Stop hook that keeps a turn alive while inventory rows are open
(Claude honors stop_hook_active + 8-block cap; Codex trust recorded 2026-09-24).

Events: gate_denied / gate_passed / inventory_closed / rewalk / escape append
to ~/.local/state/agent-quality/events.jsonl (schema_version 1; no secrets).

## Install / rollback on the host

Install: `hooks/install.sh <staging>` (backs up replaced files). Rollback:
```
cp ~/.agent-hooks/backups/qa-ship-gate-2026-09-24/coordinator-hook-pretool.sh ~/.agent-hooks/coordinator-hook-pretool.sh
cp ~/.agent-hooks/backups/qa-ship-gate-2026-09-24/claude-settings.json ~/.claude/settings.json
cp ~/.agent-hooks/backups/qa-ship-gate-2026-09-24/codex-hooks.json ~/.codex/hooks.json && python3 ~/.agent-hooks/codex-hook-trust.py --trust
rm -f ~/.agent-hooks/qa-ship-gate-hook.sh ~/.agent-hooks/qa-stop-hook.sh
for h in ~/.agents ~/.bb ~/.claude ~/.codex; do rm -rf "$h/skills/qa-sweep"; done
```

## Repo opt-in steps

1. `mkdir .qa && cp <config.example.json> .qa/config.json` (edit personas,
   workflows, deployed_check) and `cp <skill>/scripts/ship-gate.py .qa/bin/ship-gate.py`.
2. Commit both; the gate is now on for everyone.
3. Adopt `templates/pre-push` into .git/hooks (and CI from `templates/qa-ci.yml`
   as a required check).
4. `.qa/` task artifacts (workflow, inventory, clusters, plan, rewalk,
   evidence) are COMMITTED with each task branch: reviewers see the inventory
   and CI re-checks it at the pushed SHA; staleness is impossible to carry
   because rewalk.sha must equal the pushed SHA.

`meaningful-tests` points here instead of carrying the pipeline as prose.

## Scope gate (2026-09-25)

`shared/scope-ledger/` holds the scope ledger skill and `scripts/scope-gate.py`, and
`hooks/scope-gate-hook.sh` is chained in `coordinator-hook-pretool.sh` after the ship gate.
From a thread that has a ledger (`~/.local/state/agent-quality/scope/<thread>.json`), a
spawn or tell must carry `serves: P<n>` for an open purpose, or `serves: revision "<quote>"`.
Threads without a ledger are never gated. Install with `hooks/install-scope-gate.sh`; it
does not reinstall qa-sweep. The fleet plugin reads the same ledger for its idle guard and
archive hold (fleet `lib/scope.ts`).
