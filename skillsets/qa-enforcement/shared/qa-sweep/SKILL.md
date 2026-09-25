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
verify_timeout: 420
verified: 2026-09-25
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

**The walk identity.** Walk as an identity that no automated suite owns. An
identity is owned when a CI workflow, or e2e setup, fixtures or teardown,
signs in as it or creates, resets or deletes its data. List the owned ones in
`.qa/config.json` `automation_identities`. If the repo has no unowned identity
for the persona, walk with the owned one only when no automated run on the
same data overlaps the walk. Check running CI before you start, and again
after you finish for any run whose interval intersected the walk window. Say
in the evidence that the identity is shared. The evidence packet records all
of it in `authentication.identity` (verified-qa-e2e evidence contract), and
the gate refuses a packet that declares a listed identity unowned. Why: on
2026-09-25 two interactive walks on meu-psi signed in as the deployed CI
suite's own e2e identities on the shared preview DB. The suite's setup
recreated their data mid-walk, the walks changed data under the suite, and a
deployed gate went 36/38 on a build that was 38/38 twelve minutes earlier.

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
- **A gate failure caused by another writer is a defect, not a flake.** When
  a gate or walk fails because something else changed the same data during
  it (a CI setup, another agent's walk, a seed job), record an inventory row
  with `"kind": "environment_contamination"` and `"writer"`: the CI run id,
  thread id or job that wrote. The gate refuses such a row without a writer.
  Never re-run the gate blind: find the writer, stop the overlap, then re-run
  and re-walk.
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

Only what SHIPS is gated (v2 + v4): **merges** (`gh pr merge` with any flags, `gh pr ready`),
**pushes whose destination is protected** — the repo's default branch plus
`protected_branches` in `.qa/config.json` (resolved from the refspec, `HEAD:dev`,
`+dev` and bare `HEAD` forms, the current branch's upstream when there is no
refspec; `--all`/`--mirror` count as protected) — **tag pushes** (`git push origin
v1.2`, `refs/tags/…`, `tag v1.2`, `--tags`/`--follow-tags`) — and **production
deploys**: `vercel --prod` / `vercel deploy --prod` / `--target production`,
`vercel promote`, `vercel redeploy`,
`netlify deploy --prod`, `fly deploy`, **releases** (`gh release create`, and
`gh release edit` with `--draft=false` or `--tag`), **any
workflow dispatch** (`gh workflow run`: deploy workflows are dispatched exactly
this way, and a name→file→jobs mapping is not decidable locally in a hook — a
false positive only asks for a completed pipeline, a false negative ships), and
a **deployments-API POST that targets production** (`vercel api …/vN/deployments`
or curl, with `target: production` in the arguments, in a readable body file
such as `--input body.json` / `-d @body.json`, or anywhere in the command text),
plus a POST to the promote API. Env prefixes and runners (`FOO=1 …`, `env`,
`npx`, `bunx`, `pnpm dlx`, …) and multi-line commands classify like the bare
command.

Free on purpose: **feature-branch pushes** (that is how previews and CI get
built), **`gh pr create`** (that is how the preview and the PR are produced),
**`bb fleet validate`** (review should see the work before the merge, not
after), **preview deploys** (`vercel deploy` without a production target, and
a `vercel api`/curl POST to `/vN/deployments` whose target is a preview — the
meu-psi pilot heals seat-blocked previews through exactly that call, and
blocking it would deadlock the pilot again), and **`vercel rollback`**
(incident recovery restores an already-shipped deployment). A deployments POST
whose body cannot be seen at hook time (built by a script or piped on stdin)
and carries no production marker anywhere in the command is allowed: the hook
gates on evidence of production. The deadlock v1 had — the re-walk must be at
the shipped SHA but the preview for that SHA only exists after the push — is
resolved: walk against the preview of your feature-branch push, then merge.

Walk freshness is checked at **every commit the command ships** (v4): for a
MERGE, `rewalk.json` must sit at the PR head SHA being merged (`gh pr view
--json headRefOid`), or one `.qa/`-only commit on top of it; for a protected
push, the pushed source commit (`feat:main` checks `feat`); for a tag push or
release, the tagged commit (else `--target`, else the remote default branch);
for a workflow dispatch, its `--ref` (else the default branch) as origin knows
it; for other deploys, the local HEAD — each with the same `.qa`-only
allowance. A walked HEAD cannot clear an unwalked tag, and a walked tag cannot
hide an unwalked branch pushed next to it.

**Deployments ship their own commit (v5).** `vercel promote <deployment>`,
`vercel redeploy <deployment>`, `vercel alias [set] <deployment> <domain>`,
`vercel rolling-release start --dpl <deployment>`, the promote and alias APIs,
and a production deployments POST naming `deploymentId` ship a deployment that
already exists, so the gate resolves the commit Vercel built it from (one
read-only `vercel api /v13/deployments/<id|url>` through the CLI's own login,
scoped by `--scope`, the URL's `teamId`, or `.vercel/project.json`) and needs a
fresh run for THAT tree (tree equivalence; the run's records may sit in HEAD's
committed tree). It denies when the deployment is unknown, the CLI is missing,
logged out or offline, the lookup overruns its 3.2 s budget (the hook itself
times out at 5 s), the deployment has no git metadata or was built dirty, or
its commit is not in the clone (`git fetch`). A production deployments-API
create whose body names a `gitSource` is checked at that commit, not HEAD. An
upload deploy (`vercel --prod`, `netlify deploy --prod`, `fly deploy`) ships the
working tree, so uncommitted changes outside `.qa/` deny it. GitHub API writes
that ship (`gh api` or curl to api.github.com: a PR merge, `merges`, release
create/publish, ref create/update, contents commits, workflow/repository
dispatch, deployments, and the GraphQL merge/ref/commit mutations) deny
outright: use the gated CLI form (`gh pr merge`, `gh release create|edit`,
`git push`, `gh workflow run`) so the shipped commit is checked. Reads and
deletes stay free. The whole hook decision is budgeted at 4.0 s, under the
host's 5 s hook timeout; anything that cannot finish in time denies.

**Releases after a merge (tree equivalence).** A release tag normally points at
the squash or merge commit on the default branch, which is never the walked PR
head. For a **tag push, `gh release create`, or a `gh workflow run` on the
default branch** (no `--ref`, or `--ref <default>`), and only for those, the
walk also covers a commit whose root tree outside `.qa/` is **identical by tree
hash** to the tree of the walked commit (the committed run's `rewalk.json`
sha, which must be present in the clone). Squash-merging an up-to-date branch
therefore ships without a second walk. If any path outside `.qa/` differs
(the base moved, or a merge brought in other changes), the combined code was
never walked. Walk the merged commit, commit the evidence as one `.qa/`-only
commit on top, and tag or dispatch that. Protected-branch pushes, merges,
non-default dispatches and other deploys keep the strict rule (walked sha or
one `.qa`-only commit on top). A commit that one command ships both as a tag
and to a protected branch is checked strictly.

The local gate (PreToolUse hook, git pre-push template) checks consistency; the
CI job is where merges are truly enforced — make it a required check. The CI
template handles merge queues (`merge_group` trigger; a queue run checks the
queued PR's head, taken from the PR number in the
`gh-readonly-queue/<base>/pr-<N>-<base-sha>` ref, never the group commit). In
husky repos the pre-push gate block goes at the **top** of `.husky/pre-push`
(see the template header): it saves the pushed refs, gates on them, and hands
them back to the husky script after it; appended after a script that reads
stdin it would see no refs and let every push through. If a ship is denied,
complete the pipeline; never delete `.qa/config.json` to dodge the gate.
