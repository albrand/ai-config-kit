---
name: assess-then-harden
description: Perform a whole-project assessment, generate or refresh knowledge docs, derive missing requirements and tickets from internal and external sources, and plan hardening work. Use when the user wants an existing project read deeply and turned into docs, gaps, QA logic, and implementation plans.
---

# Assess Then Harden

Suggested user-facing command name: `/assess-then-harden`.

Use this skill to understand an existing project end to end, turn that understanding into durable knowledge, identify missing requirements or tickets, and plan hardening work against source-of-truth material such as docs, tickets, designs, runbooks, PRs, support reports, or external specs.

## Workflow

1. Read `ECOSYSTEM_TERRAFORM_GUIDE.md` and `skillsets/ecosystem-terraform/references/ecosystem-output-contract.md` when available.
2. Extract project path, external sources, expected docs location, issue tracker, target audience, hardening goals, known risks, and whether the user expects writes or only an assessment.
3. Verify capabilities before promising full coverage: repo read/write access, issue tracker, docs system, GitHub, Figma, deployment/log systems, browser access, and sub-agent or parallel processing.
4. Ask targeted questions when missing answers materially change assessment scope, docs format, ticket destination, external-source priority, or approval to use parallel agents.
5. Present a short execution plan before writes: source discovery, knowledge-doc shape, gap analysis method, ticketing strategy, QA/business-logic matrix, validation, and stop conditions.
   Include a challenge pass for directives, journals, memories, cached
   conclusions, and prior project patterns before turning observations into
   hardening rules. Use an independent model/counterpart critique when available
   and include the authorization sentence in advisor briefs.
6. Inspect project evidence broadly:
   - Repo instructions, README, architecture docs, ADRs, project docs, package/build config, CI, tests, env docs, deployment docs, and runbooks.
   - Entry points, routes, handlers, services, data models, auth, integrations, state, UI flows, scripts, and generated artifacts.
   - Existing tickets, roadmap artifacts, PRs, review comments, designs, specs, support notes, and external requirements.
7. Produce or refresh knowledge docs with current-state architecture, domain glossary, source-of-truth map, runtime boundaries, integration map, quality gates, and known risks. Keep business terms clear for non-technical users.
8. Derive gaps: missing requirements, missing tests, undocumented business rules, unclear ownership, stale docs, weak CI gates, untracked risks, missing tickets, duplicate tickets, and design/runtime mismatches.
9. Build a hardening roadmap with PR-sized tickets and traceability from every recommendation to source evidence.
10. Build a business-logic QA matrix from docs and tickets. Include negative paths, permissions, state transitions, data lifecycle, integrations, and edge cases where relevant.
11. Stop for approval before creating or editing tracker items, changing docs at scale, launching sub-agent swarms, or starting implementation.
12. Validate final assessment by re-reading generated docs, checking traceability, ensuring no private/sensitive facts leak into shared artifacts, and reporting uninspected areas.

## Guardrails

- Do not claim the entire project was read if capability, time, or path access limited coverage.
- Do not create missing requirements from imagination; tie each gap to a source or mark it as a hypothesis.
- Do not mutate boards, docs, cloud, or repositories without approval.
- Do not collapse implementation planning into vague "cleanup" tickets.
- Do not hide uncertainty to make the hardening plan look complete.

## Output

Return an assess-then-harden result with:

- Coverage map.
- Knowledge docs created, updated, or proposed.
- Source-of-truth map.
- Missing requirements and ticket gaps.
- Hardening roadmap and ticket list.
- Business-logic QA matrix summary.
- Capability and approval gates.
- Validation, uninspected areas, and residual risk.
