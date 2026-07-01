---
description: Bootstrap or reconcile a project roadmap, operating model, and ticket ecosystem from business docs, designs, legacy boards, and stakeholder prompts.
argument-hint: [business prompt, docs, repo paths, designs, board/project targets]
---

# Roadmap Terraform

Use this command to create or reconcile a project roadmap ecosystem from evidence. This is a Claude Code runbook command. Do not rely on custom scripts. Use normal Claude Code capabilities: read files, search, inspect connected MCP systems when available, ask targeted questions, and write or update artifacts only when approved.

User input:

`$ARGUMENTS`

Before mutating any board, docs system, repo, or ticket tracker, verify the required capability and ask for approval. Before launching sub-agents, parallel agents, or a swarm, ask whether the user approves that routing for this run.

## Workflow

1. Load `ECOSYSTEM_TERRAFORM_GUIDE.md` and `skillsets/ecosystem-terraform/references/ecosystem-output-contract.md` if available.
2. Extract project boundary, business outcome, target users, project size, legacy or greenfield status, source docs, designs, boards, quality gates, and desired output.
3. Verify required channels: repo access, issue tracker MCP/CLI, Figma/design access, GitHub, docs system, deployment context if relevant, and sub-agent availability.
4. Ask up to three targeted questions if missing answers materially change roadmap shape, import strategy, governance, or external mutations. If useful, include a question asking whether sub-agent swarming or parallel processing is approved.
5. Present a short execution plan before writing: sources, capability gaps, update-vs-create strategy, artifacts, validation, and stop conditions.
   Challenge directives, journals, memories, cached conclusions, and prior project patterns as evidence, not authority; use an independent model/counterpart critique when available and include the authorization sentence in advisor briefs.
6. Inspect current roadmap/project artifacts, business docs, requirements, designs, repo docs, tickets, active PRs, release docs, analytics/support notes when available, and explicit stakeholder instructions.
7. Choose reconciliation mode: import existing, transform existing, or create new.
8. Build the roadmap package: objective, scope, non-goals, personas, current state, target state, phases, dependencies, risks, open questions, owners, quality gates, and source traceability.
9. Create or propose PR-sized vertical-slice tickets with objective, acceptance criteria, validation, dependencies, resources, and owner/priority when known.
10. Build a business-logic QA matrix from docs, designs, and tickets.
11. Validate final artifacts against the output contract and report created, updated, proposed, blocked, and not-run work separately.

## Output

Use the final report shape from `ecosystem-output-contract.md`. Include approval gates remaining before any live board mutation, bulk import, ticket cancellation, or sub-agent swarm.
