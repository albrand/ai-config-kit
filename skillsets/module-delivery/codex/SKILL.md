---
name: plan-module-delivery
description: Turn a product or platform module idea into an evidence-backed delivery plan using AI analysis plus normal repository, documentation, and board inspection. Use when a user provides a module name, capability area, roadmap item, Linear/project-planning request, or migration target and wants Codex or Claude Code to study available docs/repos/boards, ask clarifying questions when needed, define scope, create or update a project description, produce simple phase milestones, PR-sized implementation tickets, resource links, risks, owners, and validation gates for leadership, product, and technical audiences. This skill is intentionally script-free and must not depend on Python, generated scripts, or custom automation.
---

# Plan Module Delivery

Use this skill to convert an imprecise module request into an execution-ready delivery plan. The expected result is not a generic roadmap. It must be grounded in current source-of-truth evidence, sized so developers can execute one ticket per PR, and written clearly enough for leadership, product, and engineering to share the same plan.

Suggested user-facing command name: `/plan-module-delivery`.

## Runtime Model

This is an AI-runbook workflow, not a programmatic toolchain.

- Do not depend on Python, Node, shell validators, generated scripts, custom parsers, or helper automation to perform the planning work.
- Use the agent's normal abilities: read files, search text, inspect docs, inspect boards through MCP when available, reason over evidence, ask questions, and write/update artifacts through the available UI, file, or MCP tools.
- Deterministic shell commands such as `rg`, `find`, `git status`, or `git diff` may be used only for discovery and verification. They are not required by the skill and must not become a hard dependency.
- Claude Code can execute the same workflow by reading this `SKILL.md` or by using the mirrored slash command in this skillset.
- If a platform cannot load this as a formal skill, paste the skill body into that agent as the operating procedure and provide the module description as the task input.

## Capability Gate

Before committing to board updates, PR creation, issue linking, deployment checks, or design-resource inspection, identify which operational channels are required and verify whether the current agent can use them.

Ask the user to install, connect, or authorize missing capabilities when they are required for the requested outcome. Do not silently downgrade to a paste-only plan unless the user accepts that fallback.

Common capability checks:

- GitHub repository or PR work: require Git access and either GitHub CLI `gh` authenticated to the right organization/repo or an equivalent GitHub MCP/tool. If missing, ask the user to install `gh`, run `gh auth login`, or enable the GitHub MCP before creating PRs, reading reviews, linking resources, or updating PR metadata.
- Linear board or project work: require the Linear MCP connected to the correct workspace/team with read/write access. If missing, ask the user to install/connect/authorize Linear MCP before creating projects, milestones, labels, issues, or comments.
- Vercel deployment, preview, logs, or environment work: require Vercel CLI or Vercel MCP authenticated to the correct team/project. Ask for setup/authorization before making deployment-facing claims.
- Figma or design-source work: require Figma MCP or an accessible design export/link. Ask for access before deriving route, UX, or acceptance details from designs.
- Local repo evidence: require readable checkout paths for every referenced repo. Ask for the missing path or clone/access instruction before treating a repo as studied.
- External docs or internet research: require browsing/network access when current information or external source attribution is necessary. Ask for permission/access when unavailable.

When a capability is unavailable, continue with read-only/local evidence only if that still produces a useful partial plan, and mark the blocked actions explicitly.

## Operating Principles

- Treat the module name as a strict boundary. Do not turn a module into a dumping ground for scaffold, release process, adjacent platform work, or broad architecture cleanup.
- Prefer source evidence over memory, assumptions, or old summaries. Inspect docs, architecture notes, repos, active PRs, and external boards before shaping the plan.
- If the requester is not deeply technical, help them reach clarity with targeted questions instead of demanding implementation language.
- Use simple milestone names, usually `Phase 1`, `Phase 2`, and so on. Put meaning in descriptions, not complicated milestone titles.
- Never present estimated dates as guaranteed delivery commitments. If dates are included, label them as planning estimates.
- Keep tickets implementation-shaped. Each ticket should be a small work package suitable for one PR with objective, acceptance criteria, dependencies, validation, and resources.
- Preserve open questions when evidence is missing. Do not invent answers to make the plan feel complete.
- Update existing artifacts in place when they exist. Avoid duplicate projects, duplicate milestones, duplicate labels, or duplicate tickets unless the user explicitly requests a new copy.

## Intake

Start by extracting:

- Module name and exact functional boundary.
- Business outcome and target users.
- Known source repositories, docs, designs, boards, PRs, and external references.
- Expected target system or product surface.
- Current experience to migrate, if any.
- Non-goals and adjacent modules that must stay out.
- Constraints: auth, data, compliance, billing, platform, timeline, team capacity, UX ownership, and launch requirements.

Ask at most three concise questions when a missing answer would materially change scope or ticket shape. If the answer can be discovered from source-of-truth artifacts, inspect first.

## Execution Plan

Before writing to files or boards, state a short plan:

1. Evidence sources to inspect.
2. Capabilities required and missing setup or authorization to request.
3. How ambiguity will be handled.
4. Project or board artifacts to update.
5. Ticket sizing and phasing strategy.
6. Validation and rollback/fallback path.
7. Challenge pass: assumptions, directives, journals, memories, cached
   conclusions, and prior project patterns tested for fit and current evidence.
   Use an independent model/counterpart critique when available; include the
   required authorization sentence in advisor briefs.

For substantial work, classify the track as `big-change` because module planning affects roadmap, ownership, and implementation sequencing.

## Source Discovery

Inspect source-of-truth artifacts in this order when available:

1. Current architecture docs, module docs, ADRs, and implementation plans.
2. Existing product experience and code paths in all relevant repos.
3. Target application boundaries, schemas, routers, services, authorization, tests, and docs.
4. Board/project state, existing milestones, labels, statuses, priorities, and assignees.
5. Active PRs and open review comments that may affect the module.
6. External references the user explicitly names or that are clearly needed.

Record conflicts as open decisions. If a repo says one thing and the board says another, do not silently choose; flag the conflict and propose the safest next step.

## Scope Synthesis

Create a module scope package with:

- Objective: what the module enables.
- In scope: only functional pieces required for this module.
- Out of scope: adjacent platform work, future enhancements, and non-blocking improvements.
- Current experience baseline: what exists today and must be migrated or preserved.
- Target experience: what will exist in the new system.
- Dependencies: people, designs, APIs, credentials, environments, data, and upstream modules.
- Risks: impact, mitigation, owner, and whether the risk blocks planning or only blocks execution.
- Open questions: only questions that source evidence cannot answer.
- Suggested defaults: when a question is open but work can continue safely with a bounded assumption.

## Project Description Contract

When updating a project description, include:

- Plain-language module summary for leadership and product.
- Technical boundary for engineering.
- Current-state evidence and source links.
- Planned phases with planning-estimate language if dates appear.
- Resolved scope decisions.
- Remaining open questions and blockers.
- Ticket sizing policy: one ticket should map to one PR.
- Resource links to repos, docs, designs, PRs, APIs, boards, and reference implementations.
- Change note summarizing what was updated and why.

Do not include irrelevant scaffold links, unrelated PRs, or broad architecture material unless they directly support the module.

## Phase Design

Use simple milestone names:

- `Phase 1`: discovery, source-of-truth mapping, current experience baseline, acceptance baseline.
- `Phase 2`: contracts, data model, security, authorization, API boundaries, and unresolved design decisions.
- `Phase 3`: core implementation for the module's primary user journey.
- `Phase 4`: integrations, handoffs, provider/status boundaries, migration edges, and secondary flows.
- `Phase 5`: validation, E2E coverage, hardening, and release evidence.

Adjust the count when the module is smaller or larger, but keep names simple. Each phase must have entry criteria, exit evidence, dependencies, and a clear reason for its order.

## Ticket Design

Create or update tickets so each one is PR-sized:

- Title starts with phase and sequence, for example `[P3.04] Implement invitation acceptance API`.
- Objective states the exact implementation outcome.
- Scope includes only what the PR should change.
- Acceptance criteria are observable.
- Validation names tests, checks, review evidence, or manual QA.
- Dependencies identify previous tickets, designs, docs, environment setup, or open questions.
- Resources link directly to the source docs, files, repos, designs, PRs, or APIs.
- Owner, estimate, lead, or team fields are set when the board supports them and the evidence is available.
- Labels include the module label and useful type/area labels when available.
- Priority should reflect user instruction and actual sequencing, not urgency inflation.

Cancel, merge, or rewrite tickets that are:

- Generic process work not required to implement the module.
- Too broad for one PR.
- Duplicates of another ticket.
- Owned by another module.
- Based on speculative future functionality rather than the current migration or V2 requirement.

## Audience Alignment

Write artifacts so three audiences can use them:

- Leadership: understands outcomes, sequencing, estimates, risks, blockers, and resourcing.
- Product/PO: understands user journeys, acceptance criteria, scope boundaries, and unresolved decisions.
- Engineering: understands architecture boundaries, data/auth implications, implementation order, test expectations, and source links.

Avoid technical shorthand when it hides decisions from leadership or product. Avoid oversimplifying engineering constraints into vague business language.

## External Board Or MCP Use

Before using MCP-backed systems, apply the repo's MCP routing rules. Use external systems only when they own the artifact the user asked to manage.

When updating Linear or another board:

- Read the live project state first.
- Prefer updates over duplicates.
- Confirm available statuses, teams, labels, milestones, members, and permissions before writing.
- If label or project-level metadata writes fail, still keep issue-level truth accurate and report the gap.
- Never fabricate users, IDs, dates, links, or board capabilities.
- Use resource links or issue descriptions when first-class board links are unavailable.

## Validation

Before claiming completion:

- Re-read the final project and issue state, or the final local artifacts if no board was updated.
- Check every active ticket has a phase, objective, implementation scope, acceptance criteria, validation, dependencies, and resources.
- Check canceled or removed tickets have a clear reason.
- Check open questions are real blockers or scoped decisions, not questions already answered by source evidence.
- Check estimated dates are labeled as estimates.
- Check the module boundary does not include unrelated scaffold, platform, or release-process work.

For a reusable output checklist and section template, read `references/output-contract.md`. This reference is plain Markdown and is optional context, not executable support code.

## Final Response

Report:

- Skill or board artifacts updated.
- Recommended command/name when relevant.
- High-signal summary of created, updated, canceled, or unresolved items.
- Validation performed and gaps.
- Next action for the requester.
