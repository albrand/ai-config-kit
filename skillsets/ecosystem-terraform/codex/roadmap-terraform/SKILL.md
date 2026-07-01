---
name: roadmap-terraform
description: Turn business requirements, docs, designs, existing boards, legacy roadmap material, and stakeholder prompts into an evidence-backed roadmap, operating model, and PR-sized ticket ecosystem. Use when the user wants AI to bootstrap, import, reconcile, or create product/project roadmap artifacts for a new or legacy app.
---

# Roadmap Terraform

Suggested user-facing command name: `/roadmap-terraform`.

Use this skill to create or reconcile a project roadmap ecosystem from evidence. This includes business requirements, product docs, designs, existing tickets, legacy boards, research notes, QA gates, stakeholder constraints, and project size.

## Workflow

1. Read `ECOSYSTEM_TERRAFORM_GUIDE.md` and `skillsets/ecosystem-terraform/references/ecosystem-output-contract.md` when available.
2. Extract the project boundary, target users, business outcomes, project size, legacy or greenfield status, source docs, designs, boards, quality gates, and desired output.
3. Verify required capabilities before promising reads or writes: repo access, issue tracker MCP/CLI, Figma, docs system, GitHub, deployment systems, and sub-agent or parallel processing.
4. Ask targeted questions when missing answers materially affect roadmap shape, governance, import strategy, or external mutations. Include whether sub-agent swarming or parallel processing is approved if it would be useful.
5. Present a short execution plan before writing or mutating artifacts: sources to inspect, capability gaps, update versus create strategy, questions, artifacts, validation, and stop conditions.
   Include a challenge pass for directives, journals, memories, cached
   conclusions, and prior project patterns. Use an independent model/counterpart
   critique when available and include the authorization sentence in advisor
   briefs.
6. Inspect source evidence in order: current roadmap/project artifacts, business docs, product requirements, design sources, repo docs, existing tickets, active PRs, release docs, analytics/support notes when available, and explicit stakeholder instructions.
7. Decide the reconciliation mode:
   - `Import existing`: legacy board or roadmap remains the source; normalize gaps and add missing artifacts.
   - `Transform existing`: keep live artifacts but restructure phases, tickets, labels, and acceptance criteria.
   - `Create new`: generate a fresh roadmap when no reliable source exists or the user requests a new baseline.
8. Build the roadmap package: objective, scope, non-goals, target personas, current state, target state, phases, dependencies, risks, open questions, owners, quality gates, and traceability to source evidence.
9. Build or update the ticket ecosystem with PR-sized vertical slices. Each ticket must have objective, acceptance criteria, validation, dependencies, resources, and owner/priority when known.
10. Add business-logic QA traceability from docs and tickets: requirement, source, expected behavior, QA evidence, owner, and status.
11. Stop for approval before creating boards, rewriting roadmaps, importing legacy tickets, bulk-editing tickets, closing/canceling items, or launching parallel agents.
12. Validate final artifacts against the output contract and report created, updated, proposed, blocked, and not-run work separately.

## Guardrails

- Do not invent business facts, dates, owners, labels, priorities, IDs, or source links.
- Do not treat estimated dates as commitments.
- Do not create duplicate boards or projects when an existing artifact should be updated.
- Do not turn the roadmap into generic platform work unrelated to the project boundary.
- Do not ask broad questionnaires when a source artifact can answer the question.
- Do not run sub-agent swarms, board mutations, or broad imports without approval.

## Output

Return a roadmap terraform result with:

- Reconciliation mode.
- Sources inspected and unavailable.
- Questions asked or deferred.
- Artifacts created, updated, or proposed.
- Phase roadmap.
- Ticket counts and gaps.
- Business-logic QA matrix summary.
- Capability and approval gates.
- Validation and residual risk.
