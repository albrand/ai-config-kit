---
name: qa-sweep
description: >
  Use in repos with a committed .qa/config.json before shipping (a protected
  push, a release, any production deploy), and whenever a workflow
  walk finds defects. Covers the full pipeline the ship-gate enforces: scope
  the workflow (P0), walk it end to end and inventory EVERY defect without
  fixing anything (P1, including defects that predate your change), cluster
  them by root cause with a repro that has failed once (P2), write one plan
  (P3), fix per cluster in a batch (P4), close the inventory, re-walk the
  whole workflow once at the batch head (P5), then ship (P6). The gate denies
  protected shipping until the pipeline is complete.
verify: 'python3 "$HOME/.agents/skills/qa-sweep/scripts/ship-gate.py" selftest'
verify_timeout: 420
verified: 2026-09-25
---
# QA sweep: discover everything, cluster, plan once, fix, re-walk

## Purpose and when to use it

Use this skill in repositories with committed `.qa/config.json` before protected shipping, a release, or production deploy, and whenever a workflow walk finds defects. The full pipeline is scope, walk and inventory, cluster, plan, fix, close inventory, re-walk, then ship. The ship gate denies protected shipping until required evidence is complete.

## Final completion claims

Across repositories, a final claim that work is done, ready, working, fixed,
tested, verified, or validated needs an evidence packet containing:

- the persona;
- the target (stack plus commit SHA, or URL plus deployment ID);
- the user outcomes attempted;
- a verdict for each outcome.

Run the workflow or its tests when you can. Only when it cannot be run now, say
`implemented; workflow NOT RUN`, name the blocker, and name what remains;
relabelling a runnable check as NOT RUN is not a fix. The Stop nudge applies even when a repository has no `.qa/`
configuration. Repositories without `.qa/config.json` do not receive the QA
ship gate, and the nudge never creates `.qa/` files or denies tool calls.

The unit of work is the workflow, not the defect in front of you. The failure
this skill exists to stop: find 1 error, fix 1, deploy 1, repeat. Every phase
below has an artifact and a checker; the ship-gate script is the enforcement,
this text is only the map. Claim rules and verdict semantics are the
`meaningful-tests` contract — nothing here weakens them.

Adapted from vercel-labs/agent-browser `dogfood` (Apache-2.0), obra/superpowers
`systematic-debugging` + `verification-before-completion`, and mattpocock/skills
`diagnosing-bugs` (MIT). See LICENSES.md. Three deliberate changes from dogfood:
the "aim for 5-10 issues then wrap up" cap is REMOVED — you walk the whole
workflow to its outcome; `agent-browser` is replaced by the bb `browser_*`
tools; and every inventory row records whether it predates this change.

## Rules and invariants

- Completion claims require the evidence packet and verdicts defined below. Run available workflows; report NOT RUN only with the blocker and remaining work.
- Walk the entire workflow, record every defect before fixing, reproduce defects, and keep the inventory complete.
- Cluster by root cause, validate repros, create one plan, and fix per cluster; after three failed attempts, stop and escalate with repro output.
- Re-walk the complete workflow once at the aggregate batch head; every step needs a verdict and evidence.
- Protected shipping remains blocked until inventory, re-walk, evidence, and commit freshness requirements pass. Never delete `.qa/config.json` to bypass the gate.

## Steps

1. Define the persona, workflow and target. Read `references/workflow-scope.md` when you reach this step.
2. Walk the entire workflow and record every defect before fixing. Read `references/walk-and-inventory.md` when you reach this step.
3. Reproduce and cluster by root cause, then make one plan. Read `references/cluster-and-plan.md` when you reach this step.
4. Fix per cluster and close one aggregate batch inventory. Read `references/fix-and-batch.md` when you reach this step.
5. Re-walk the complete workflow at the aggregate batch head and attach evidence. Read `references/rewalk.md` when you reach this step.
6. Follow the protected shipping rules and freshness checks. Read `references/ship-gate.md` when you reach this step.
