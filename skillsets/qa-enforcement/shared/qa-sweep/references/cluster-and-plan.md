# P2 root-cause clustering and P3 planning procedures

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
