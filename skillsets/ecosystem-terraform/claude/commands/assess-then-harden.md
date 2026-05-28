---
description: Read an existing project deeply, generate knowledge docs, identify missing requirements and tickets, and plan hardening work against source evidence.
argument-hint: [project path, external docs/tickets/designs, target docs or tracker]
---

# Assess Then Harden

Use this command to assess an existing project end to end, turn the assessment into durable knowledge docs, derive missing requirements and tickets, and plan hardening work. This is a Claude Code runbook command. Do not claim full coverage unless the inspected sources support it.

User input:

`$ARGUMENTS`

Before mutating docs, issue trackers, repositories, cloud/deployment systems, or boards, verify the required capability and ask for approval. Before launching sub-agents, parallel agents, or a swarm, ask whether the user approves that routing for this run.

## Workflow

1. Load `ECOSYSTEM_TERRAFORM_GUIDE.md` and `skillsets/ecosystem-terraform/references/ecosystem-output-contract.md` if available.
2. Extract project path, external sources, expected docs location, issue tracker, target audience, hardening goals, known risks, and whether the user expects writes or assessment only.
3. Verify required channels: repo read/write access, issue tracker, docs system, GitHub, Figma/design access, deployment/log systems, browser access, and sub-agent availability.
4. Ask up to three targeted questions when missing answers materially change scope, docs format, ticket destination, external-source priority, or approval to use parallel agents.
5. Present a short execution plan before writes: source discovery, knowledge-doc shape, gap analysis method, ticketing strategy, QA/business-logic matrix, validation, and stop conditions.
6. Inspect repo instructions, README, architecture docs, ADRs, package/build config, CI, tests, env docs, deployment docs, runbooks, entry points, routes, handlers, services, data models, auth, integrations, state, UI flows, scripts, and generated artifacts.
7. Inspect external source evidence: existing tickets, roadmap artifacts, PRs, review comments, designs, specs, support notes, and explicit requirements.
8. Produce or refresh knowledge docs: current architecture, domain glossary, source-of-truth map, runtime boundaries, integration map, quality gates, and known risks.
9. Derive missing requirements, ticket gaps, stale docs, weak CI gates, untracked risks, missing tests, duplicate tickets, and design/runtime mismatches.
10. Build a hardening roadmap with PR-sized tickets and source traceability.
11. Build a business-logic QA matrix from docs and tickets.
12. Validate final assessment by re-reading generated docs, checking traceability, scanning for sensitive facts in shared artifacts, and reporting uninspected areas.

## Output

Use the final report shape from `ecosystem-output-contract.md`. Include coverage limits, uninspected areas, approval gates, and residual risk.
