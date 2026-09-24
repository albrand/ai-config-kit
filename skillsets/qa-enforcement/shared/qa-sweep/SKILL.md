---
name: qa-sweep
description: >
  Use in repos with a committed .qa/config.json before shipping (git push,
  gh pr create/merge, bb fleet validate, any deploy), and whenever a workflow
  walk finds defects. Covers the full pipeline the ship-gate enforces: scope
  the workflow (P0), walk it end to end and inventory EVERY defect without
  fixing anything (P1, including defects that predate your change), cluster
  them by root cause with a repro that has failed once (P2), write one plan
  (P3), fix per cluster (P4), re-walk the whole workflow at the new SHA (P5),
  then ship (P6). The gate denies the ship until the pipeline is complete.
verify: 'python3 "$HOME/.agents/skills/qa-sweep/scripts/ship-gate.py" selftest'
verified: 2026-09-24
---

# QA sweep: discover everything, cluster, plan once, fix, re-walk

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

## P0 Scope: `.qa/workflow.json`

Name the persona, the entry point, the user-visible outcome, every step
between them, and the target (URL plus the SHA being tested). A repo-level
`.qa/config.json` (committed) lists the repo's personas and workflows and is
what turns the gate on; `workflow.json` names one of those workflows.

```json
{"workflow": "invite-and-accept", "persona": "member", "entry": "/invite link from email",
 "outcome": "lands in workspace with member rights", "steps": ["open invite", "accept", "first login"],
 "target": {"url": "https://app.example.test", "sha": "<full sha>"}}
```

## P1 Walk and inventory: `.qa/inventory.jsonl` — no fixing

Walk the whole workflow with the bb `browser_*` tools as the persona would.
Rules:

- **Walk to the end.** No issue-count cap, no early wrap-up. If step 3 is
  broken, you still attempt steps 4 and 5 (a later step may be reachable via
  back/refresh, and its state is evidence).
- **Record every defect, including ones you did not cause.**
  `predates_change: true` is a column, never a dismissal — a user hitting the
  wall does not care which commit built it.
- **Do not fix anything yet.** Fixing during the walk truncates the inventory.
  Append each row the moment you see it; never batch at the end.
- Match evidence to the defect: interactive failures need the step sequence
  and the broken state (snapshot refs); visible-on-load defects need one
  annotated screenshot ref. Verify once that it reproduces before recording.
- Check the console alongside the UI, and cover the unhappy paths (see
  references/walk-checklist.md): wrong role, missing prerequisite, invalid
  input, denied permission, and every escape hatch (cancel, back, close,
  undo, retry, log out).

One JSON object per line:

```json
{"id": "R1", "step": "open invite", "symptom": "invite link 404s for expired-domain accounts",
 "evidence": "snap-r1-seq", "predates_change": false, "severity": "high", "status": "open"}
```

`status` is `open` until fixed and verified, then `closed`; or `fail_escalated`
with an `escalation` reference (ticket/user decision) when you are not
authorized to fix it. Zero rows is a valid inventory only if the walk reached
the outcome.

## P2 Cluster: `.qa/clusters.json` — root cause, red repro

Group rows that share a root cause, not a symptom. For every cluster write a
hypothesis (the causal story) and a repro command, and **make that repro fail
once before trusting it** — a repro that never failed proves nothing (a green
check you have never seen fail). Read the error fully, reproduce consistently,
and only then form the hypothesis; no fixes before the root-cause story exists
for every cluster.

```json
{"clusters": [{"id": "CL-1", "hypothesis": "invite token validated before domain check rejects valid accounts",
               "repro_command": "make repro-cl1", "repro_failed_once": true}],
 "mapping": {"R1": "CL-1", "R2": "CL-1"}}
```

Every row must map to a cluster; `cluster-check` (scripts/cluster-check)
verifies rows, clusters, repros, and plan coverage.

## P3 Plan once: `.qa/plan.md`

One plan covering every cluster id. Not one plan per defect — the clusters
exist so the plan is small. Fixing rewrites the plan only when a hypothesis is
disproven, never to add a newly-found defect silently (that defect goes
through P1/P2 first).

## P4 Fix per cluster

One commit per cluster, its repro going red to green. After the fix, re-run
the cluster's repro and the focused tests covering the change. After 3 failed
attempts on one cluster, stop and escalate with the repro output.

## P5 Re-walk: `.qa/rewalk.json` + `.qa/evidence.json`

At the new SHA, walk the ENTIRE workflow again — including steps you never
touched. Every workflow step gets a verdict (only PASS clears the gate) and
evidence. `rewalk.json` records the SHA; the gate rejects a re-walk whose SHA
is not the one being shipped. Write `.qa/evidence.json` as a
`claim_e2e_complete` packet (verified-qa-e2e evidence contract) — the gate
runs `qa-e2e-gate.mjs check` on it. Then record the events:

```sh
python3 <skill-dir>/scripts/ship-gate.py record inventory-closed   # after P1 rows close
python3 <skill-dir>/scripts/ship-gate.py record rewalk             # after P5
python3 <skill-dir>/scripts/ship-gate.py record escape --source sentry --ref <id>  # on any escape
```

## P6 Ship

Only what SHIPS is gated (v2): **merges** (`gh pr merge` with any flags, `gh pr ready`),
**pushes whose destination is protected** — the repo's default branch plus
`protected_branches` in `.qa/config.json` (resolved from the refspec, `HEAD:dev`
forms, the current branch's upstream when there is no refspec; `--all`/`--mirror`
count as protected) — and **production deploys** (`vercel --prod` /
`vercel deploy --prod` / `vercel promote`, `netlify deploy --prod`, `fly deploy`).

Free on purpose: **feature-branch pushes** (that is how previews and CI get
built), **`gh pr create`** (that is how the preview and the PR are produced),
and **`bb fleet validate`** (review should see the work before the merge, not
after). The deadlock v1 had — the re-walk must be at the shipped SHA but the
preview for that SHA only exists after the push — is resolved: walk against
the preview of your feature-branch push, then merge.

Walk freshness for a MERGE: `rewalk.json` must sit at the PR head SHA being
merged (`gh pr view --json headRefOid`), or one `.qa/`-only commit on top of
it. For pushes and deploys, the shipped HEAD with the same allowance. The
local gate (PreToolUse hook, git pre-push template) checks consistency; the
CI job is where merges are truly enforced — make it a required check. If a
ship is denied, complete the pipeline; never delete `.qa/config.json` to
dodge the gate.
