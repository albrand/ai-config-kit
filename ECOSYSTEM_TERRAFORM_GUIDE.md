# Ecosystem Terraform Invitation And Prompt Guide

Use this guide when you want an AI agent to help create, reconcile, or harden the operating system around a project.

Ecosystem terraform is for moments like:

- Starting work with a new client, product, project, or internal platform.
- Turning business material, docs, designs, and tickets into an executable roadmap.
- Bootstrapping the technical side: repo setup, local environments, quality gates, CI/CD, PR checks, release gates, and AI developer workflows.
- Reading an existing project deeply, creating knowledge docs, identifying missing requirements, and planning hardening work.

The workflows are designed for Claude Code users first, with Codex and generic AI fallbacks.

## Choose A Command

Use `/roadmap-terraform` when the main problem is product, roadmap, project operating model, tickets, phases, business logic, or QA traceability.

Use `/tech-terraform` when the main problem is technical scaffolding, stack decisions, local environments, validation commands, CI/CD, PR checks, security scans, deployment gates, observability, or AI developer workstreams.

Use `/assess-then-harden` when the project already exists and you need the AI to read it, create or refresh knowledge docs, find missing requirements, create ticket gaps, and plan hardening.

Use `/plan-module-delivery` when the scope is one module or capability area rather than the whole project ecosystem.

## What To Provide

Give the agent as much source material as you safely can:

- Project or product name.
- Business goal and target users.
- Current docs, PRDs, designs, tickets, boards, and roadmap links.
- Repo paths and important branches.
- Whether the project is new, legacy, or a migration.
- What systems may be read or changed: issue tracker, GitHub, Figma, cloud, deployment provider, docs system, secret manager, or CI provider.
- Whether you want live external-system updates or paste-ready artifacts only.
- Whether sub-agent swarming or parallel processing is approved for this run.
- Any quality requirements: test strategy, CI checks, security scans, release gates, compliance, uptime, or review policy.

Do not paste secrets. Prefer secret names, owners, scopes, and storage locations.

## Approval Gates

The agent should stop and ask before:

- Creating or rewriting roadmaps, boards, projects, repositories, CI workflows, or cloud resources.
- Importing, closing, canceling, deleting, or bulk-editing tickets.
- Changing branch protections, required checks, deploy settings, secrets, IAM, or production infrastructure.
- Running a sub-agent swarm or broad parallel processing.
- Choosing between competing architecture, cloud, auth, data, or compliance directions.
- Treating estimated dates as commitments.

If an integration is not connected, the agent should still produce a paste-ready artifact and mark live mutation as blocked.

## Prompt Samples

### 1. Roadmap Terraform From Business Docs

```text
/roadmap-terraform

We are starting a new project from the attached business requirements, product notes, and Figma designs.

Please create a project roadmap ecosystem:
- Ask only questions that materially change the roadmap or ticket shape.
- Tell me what MCP or external connections you need before writing to any board.
- Create a roadmap with phases, risks, dependencies, and open questions.
- Produce PR-sized tickets with acceptance criteria, validation, dependencies, and source links.
- Build a business-logic QA matrix from the docs and designs.
- Do not create or mutate any board until I approve the proposed structure.
```

### 2. Roadmap Terraform For A Legacy Board

```text
/roadmap-terraform

We already have an existing roadmap and tickets, but they are messy.

Use the current board and docs as source evidence. Reconcile the roadmap instead of creating a duplicate:
- Identify duplicate, too-broad, stale, or speculative tickets.
- Propose what to merge, rewrite, cancel, or keep.
- Preserve useful legacy context.
- Create a clean phase plan and one-ticket-per-PR structure.
- Ask before closing, deleting, moving, or bulk-editing any ticket.
```

### 3. Tech Terraform For A New App

```text
/tech-terraform

Bootstrap the technical operating system for a new app.

Stack preference:
- <frontend/backend/database/deployment/provider details or "discover from docs">

Please assess and scaffold everything useful:
- Local validation commands: format, lint, typecheck, tests, build, codegen/schema, migrations, docs.
- CI/CD checks: install/cache, changed-surface checks, full suite, build artifacts, preview/deploy checks, environment validation, rollback and release gates.
- PR checks: PR template, required checks, CODEOWNERS/reviewers, branch protection, high-signal AI review, required PR evidence.
- Security checks: dependency audit, license policy, secret scanning, SAST, container/IaC scanning where relevant, auth/data boundary checks.
- Runtime checks: health, smoke, observability, logging, alerts, post-deploy verification.
- AI workstreams: repo instructions, Claude Code commands, Codex skills, handoff format, review prompts, QA matrix prompts.

Before changing cloud, CI, repos, secrets, or branch protection, show me the plan and ask for approval.
```

### 4. Tech Terraform For Existing Repos

```text
/tech-terraform

Assess the existing implementation in these repo paths:
- <repo path 1>
- <repo path 2>

Build a technical quality layer matrix with status for each layer:
- present
- needs update
- missing
- not applicable
- blocked

For every missing or weak layer, either scaffold the local file if it is safe and approved, or create a PR-sized ticket with exact acceptance criteria and validation.

Do not mutate cloud resources, secrets, CI settings, branch protections, or deployment projects without approval.
```

### 5. Assess Then Harden A Project

```text
/assess-then-harden

Read this project deeply and turn it into knowledge plus a hardening plan.

Sources:
- Repo path: <path>
- Docs: <paths or links>
- Designs: <paths or links>
- Tickets/board: <tracker or paste>

Output:
- Current architecture and source-of-truth map.
- Domain glossary.
- Runtime boundaries and integration map.
- Missing requirements and stale docs.
- Missing tests, weak gates, or untracked risks.
- Business-logic QA matrix from tickets and docs.
- Hardening roadmap with PR-sized tickets.

Ask before mutating docs, tickets, boards, cloud/deploy systems, or running sub-agent swarms.
```

### 6. Single Prompt For Non-Technical Operators

```text
/roadmap-terraform

I want you to help me turn this project idea into an execution-ready development system.

I may not know every technical detail. Please:
- Read the material I provide.
- Ask only the questions that change the next important decision.
- Recommend a default answer when the evidence supports one.
- Tell me what access you need and why.
- Produce a plain-language roadmap, PR-sized tickets, QA matrix, and approval gates.
- Keep anything technical traceable enough for engineers to execute.
- Do not mutate external systems until I approve.
```

### 7. Combined Bootstrap Sequence

Use this when the project needs both business and technical setup.

```text
First run:
/roadmap-terraform
Use the docs, designs, and current board to create or reconcile the roadmap, phases, PR-sized tickets, and QA matrix. Stop before external mutations.

Second run after roadmap approval:
/tech-terraform
Use the approved roadmap and repo stack to scaffold the technical operating system: local validation, CI/CD, PR checks, security, runtime validation, release gates, and AI workstreams. Stop before cloud, CI, branch protection, or secret mutations.

Third run for existing or inherited code:
/assess-then-harden
Read the repo and external sources, generate knowledge docs, identify implementation gaps, and create hardening tickets tied back to the roadmap and quality gates.
```

## Expected Output Shape

Every ecosystem terraform run should report:

- Workflow used.
- Sources inspected and unavailable.
- Questions asked, answered, deferred, or defaulted.
- Capabilities verified, blocked, or not used.
- Artifacts created, updated, proposed, or left unchanged.
- External mutations performed, blocked, or not requested.
- Ticket counts and quality of ticket shape.
- Business-logic QA matrix or technical quality layer matrix.
- Quality gates passed, failed, blocked, skipped, or not run.
- Approval gates remaining.
- Residual risk.
- Smallest useful next action.

## Installation Reminder

Claude Code:

```text
Copy skillsets/ecosystem-terraform/claude/commands/*.md to .claude/commands/ or ~/.claude/commands/.
Run /roadmap-terraform, /tech-terraform, or /assess-then-harden with one of the prompts above.
```

Codex:

```text
Copy each skillsets/ecosystem-terraform/codex/<skill-name>/SKILL.md into <CODEX_HOME>/skills/<skill-name>/SKILL.md.
Provide this guide plus skillsets/ecosystem-terraform/references/ecosystem-output-contract.md when invoking the workflow.
```

Generic AI:

```text
Paste CONFIG_KIT_AI_PROMPT.md, this guide, skillsets/ecosystem-terraform/README.md, and skillsets/ecosystem-terraform/references/ecosystem-output-contract.md.
Then paste the relevant sample prompt and source material.
```
