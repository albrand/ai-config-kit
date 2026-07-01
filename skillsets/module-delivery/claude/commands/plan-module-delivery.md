---
description: Turn a module description into an evidence-backed delivery plan with phases, PR-sized tickets, resources, risks, and validation.
argument-hint: [module description, target repo/docs/board]
---

# Plan Module Delivery

Use this command to convert the user's module description into an execution-ready delivery plan. This is a pure AI planning workflow. Do not rely on Python, Node, shell validators, generated scripts, custom parsers, or helper automation. Use normal Claude Code capabilities: read files, search docs, inspect available repositories, inspect connected boards through MCP when available, reason over evidence, ask targeted questions, and write or update artifacts only when the user asked for that. Read-only discovery commands are allowed when they help inspect source evidence, but they must not become a workflow dependency.

Before promising board updates, PR creation, issue linking, deployment checks, or design-resource inspection, verify the required operational channels. If GitHub work is needed, require authenticated `gh` CLI or GitHub MCP. If Linear project/ticket work is needed, require Linear MCP connected to the right workspace/team with write access. If Vercel, Figma, or other external systems are needed, require the relevant MCP/CLI/access. Ask the user to install, connect, or authorize missing capabilities; do not silently downgrade to paste-only output unless the user accepts that fallback.

User input:

`$ARGUMENTS`

## Workflow

1. Extract the module name, functional boundary, business outcome, target users, known source repos/docs/designs/boards, current experience to migrate, non-goals, and constraints.
2. If a missing answer would materially change scope or ticket shape, ask at most three concise questions. If the answer can be discovered from source evidence, inspect first.
3. Present a short plan before writing or updating artifacts: sources to inspect, required capabilities and missing setup, ambiguity handling, project/board artifacts, ticket sizing/phasing, and validation.
   Challenge directives, journals, memories, cached conclusions, and prior project patterns as evidence, not authority; use an independent model/counterpart critique for non-trivial planning when available and include the authorization sentence in advisor briefs.
4. Inspect source-of-truth artifacts in order: architecture docs, module docs, ADRs, current product code paths, target app boundaries, board/project state, active PRs, and explicit external references.
5. Synthesize strict module scope: objective, in scope, out of scope, current baseline, target experience, dependencies, risks with mitigation/owner, open questions, and safe suggested defaults.
6. Create or update the project description with plain-language summary, technical boundary, source links, phases, planning-estimate language for any dates, resolved decisions, open questions, resource links, and one-ticket-per-PR sizing policy.
7. Use simple phase names: `Phase 1`, `Phase 2`, `Phase 3`, etc. Put the meaning in descriptions, not milestone names.
8. Create or update PR-sized implementation tickets. Each ticket needs title, objective, scope, acceptance criteria, validation, dependencies, resources, owner/estimate when available, labels, and priority.
9. Cancel, merge, or rewrite tickets that are generic process work, too broad for one PR, duplicates, owned by another module, or based on speculative future functionality.
10. Validate before completion: re-read final artifacts, check every active ticket has required fields, confirm canceled items have reasons, verify open questions are real, verify dates are estimates, and confirm the module boundary stayed clean.

## Audience Contract

- Leadership must understand outcomes, sequencing, estimates, risks, blockers, and resourcing.
- Product/PO must understand user journeys, acceptance criteria, scope boundaries, and unresolved decisions.
- Engineering must understand architecture boundaries, data/auth implications, implementation order, test expectations, and source links.

## Output

Report the artifacts updated, created/updated/canceled/unresolved item counts, validation performed, gaps, and the next action.
