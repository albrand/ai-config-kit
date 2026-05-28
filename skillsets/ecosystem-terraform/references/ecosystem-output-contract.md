# Ecosystem Terraform Output Contract

Load this reference before producing final artifacts for `/roadmap-terraform`, `/tech-terraform`, or `/assess-then-harden`.

## Shared Capability Gate

Before mutating any external system, verify the required channel and ask for approval:

| Capability | Required before |
| --- | --- |
| GitHub CLI or GitHub MCP | Creating repos, issues, PRs, labels, milestones, comments, or review comments. |
| Linear, Jira, Notion, or tracker MCP | Creating or changing projects, epics, issues, statuses, owners, labels, or roadmaps. |
| Figma MCP or accessible export | Deriving UX scope, acceptance criteria, or design QA from designs. |
| Cloud CLI or cloud MCP | Reading or mutating cloud resources, IAM, secrets, infra, logs, or deploy targets. |
| Vercel or deployment MCP/CLI | Reading or mutating environments, previews, deploys, logs, domains, or protection rules. |
| Secret manager access | Reading, writing, syncing, or documenting secret names and ownership. |
| Sub-agent or parallel processing | Launching multiple agents, swarms, or parallel workers. |

If a capability is missing, provide a paste-ready plan and mark live mutation as blocked. Do not fabricate IDs, users, labels, dates, credentials, URLs, provider state, or board capabilities.

## Mandatory Questions Policy

Ask concise questions when the answer changes:

- Project boundary or non-goals.
- Legacy import versus new setup.
- Ownership, approval, or governance.
- External-system write permissions.
- Target issue tracker or roadmap system.
- Quality gate strictness.
- Cloud or secret-handling authority.
- Whether sub-agent swarming or parallel processing is approved for this run.

Do not ask for facts that can be safely discovered from the provided repo, docs, designs, or board. Ask at most three questions at a time unless the user explicitly requests a full intake questionnaire.

## Artifact Contract

Every final artifact set should include:

- `Objective`: business or technical outcome.
- `Source Evidence`: docs, repositories, tickets, designs, PRs, deployments, cloud accounts, and decision records inspected.
- `Current State`: what exists now, including legacy assets or missing evidence.
- `Target State`: what should exist after the bootstrap or hardening pass.
- `Scope`: in scope, out of scope, and assumptions.
- `Operating Model`: owners, approvals, ceremonies, update cadence, and decision log path.
- `Roadmap Or Technical Phases`: ordered phases with entry criteria, exit evidence, dependencies, and rollback/fallback.
- `Tickets`: PR-sized work items with objective, acceptance criteria, validation, dependencies, resources, and owner when available.
- `Quality Gates`: checks tied to business logic, docs, designs, tickets, code, CI, release, security, data, and operations.
- `Risks`: risk, impact, mitigation, owner, and blocking status.
- `Open Questions`: only questions not answerable from source evidence.
- `Next Actions`: smallest approved next step and approval gates.

## Ticket Contract

Each generated or updated ticket must be independently grabbable:

- Title with phase or workstream prefix.
- Objective in user/business terms.
- Implementation scope limited to one PR.
- Acceptance criteria that can be observed or tested.
- Validation commands, manual QA, design checks, or business-rule checks.
- Dependencies on prior tickets, designs, docs, environments, secrets, or decisions.
- Resource links to exact docs, designs, files, APIs, PRs, or external systems.
- Labels/status/owner/priority only when the destination tracker supports them and the evidence is known.

Reject, merge, or rewrite tickets that are duplicates, horizontal layers without user-verifiable value, too broad for one PR, process-only placeholders, or speculative future work.

## Business Logic QA Contract

For QA derived from tickets and docs, build a traceability matrix:

| Requirement | Source | Expected behavior | Test or QA evidence | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| `<requirement>` | `<ticket/doc/design>` | `<observable behavior>` | `<test/check/manual QA>` | `<owner or unknown>` | `<ready/blocked/gap>` |

Include negative paths, boundary cases, permissions, state transitions, data lifecycle, integrations, and reporting/analytics expectations when relevant.

## Technical Quality Scaffold Contract

For `/tech-terraform`, assess existing implementation and scaffold or propose every quality layer that is useful for the stack and risk profile.

At minimum, evaluate:

- Local developer validation: format, lint, typecheck, unit tests, integration tests, e2e or smoke tests, build, codegen/schema checks, migration checks, seed checks, and docs checks.
- CI/CD checks: install/cache strategy, changed-surface checks, full-suite checks, build artifacts, preview/deploy checks, environment validation, migration dry runs, rollback checks, and release promotion gates.
- PR checks: PR template, required checks, CODEOWNERS or reviewers, branch protection, status naming, review automation, high-signal AI review, stale or duplicate review prevention, and required evidence in PR bodies.
- Security and compliance: dependency audit, license policy, secret scanning, SAST where available, container/image scanning, IaC scanning, auth/data boundary tests, environment variable schema checks, and least-privilege review.
- Runtime confidence: health checks, smoke tests, observability hooks, logging policy, alerting, error budget or incident notes, backup/restore checks, and post-deploy verification.
- AI developer workstreams: repo instructions, Claude Code commands, Codex skills, agent handoff format, review prompts, QA matrix prompts, and framework adoption checks.

For each layer, report one of:

- `present`: already exists and is usable.
- `needs update`: exists but is incomplete, stale, or misaligned.
- `missing`: should be scaffolded or ticketed.
- `not applicable`: explain why.
- `blocked`: needs approval, access, or external capability.

When write access and approval exist, scaffold the missing local files or workflow changes. When live mutation is unapproved or unavailable, produce exact tickets, file plans, or paste-ready artifacts instead.

## Approval Gates

Stop and ask before:

- Creating or replacing a roadmap, board, or project.
- Importing legacy tickets into a new structure.
- Deleting, closing, canceling, or bulk-editing tickets.
- Creating repositories, branches, CI pipelines, deploy projects, cloud resources, or secrets.
- Running sub-agent swarms or broad parallel processing.
- Choosing between competing architecture, cloud, data, auth, or compliance directions.
- Treating estimated dates as commitments.

## Final Report

Use this close-out shape:

```md
Ecosystem terraform result:
- Workflow: <roadmap-terraform|tech-terraform|assess-then-harden>
- Artifacts created: <list or "None">
- Artifacts updated: <list or "None">
- Proposed only: <list or "None">
- External mutations: <performed|blocked|not requested>
- Questions asked: <answered/deferred/defaulted summary>
- Capabilities: <verified/blocked/not used>
- Sources inspected: <summary>
- Tickets: <created/updated/proposed/canceled/blocked counts>
- Quality layer matrix: <present/needs update/missing/not applicable/blocked summary, required for tech-terraform>
- Quality gates: <passed/failed/blocked/skipped/not run>
- Approval gates remaining: <list or "None">
- Residual risk: <risk or "None identified">
- Next action: <smallest useful step>
```
