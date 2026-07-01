---
name: tech-terraform
description: Bootstrap or reconcile the technology side of a project from a stack prompt, existing repos, infrastructure choices, cloud/provider access, local environment needs, CI/CD gates, PR automation, and AI developer workstreams. Use when the user wants a project-agnostic technical framework setup plan or live setup actions.
---

# Tech Terraform

Suggested user-facing command name: `/tech-terraform`.

Use this skill to create or reconcile the technical operating system for a project. It covers stack selection or discovery, repositories, local development, secrets, cloud connections, CI/CD, PR review automation, quality gates, observability, agent skills, and developer workstreams. It must assess the existing implementation and scaffold or propose every useful quality gate, validation, CI/CD check, and PR check for the stack and risk profile.

## Workflow

1. Read `ECOSYSTEM_TERRAFORM_GUIDE.md` and `skillsets/ecosystem-terraform/references/ecosystem-output-contract.md` when available.
2. Extract target stacks, current repos, legacy constraints, cloud/provider preferences, runtime environments, deployment model, CI/CD requirements, PR review expectations, agent tooling, compliance needs, and desired write scope.
3. Verify capabilities before promising setup: repo write access, GitHub, package manager, cloud CLI/MCP, Vercel/deployment tools, secret manager, CI provider, design/documentation systems, and sub-agent or parallel processing.
4. Ask targeted questions when missing answers materially change stack, infrastructure authority, secret handling, environment shape, quality gates, or automation behavior. Ask for approval before any cloud mutation, repo creation, CI mutation, secret handling, or sub-agent swarm.
5. Present a short execution plan before writes: discovery sources, capability gaps, stack assumptions, artifacts to create/update, quality layers to assess, validation, rollback/fallback, and approval gates.
   Include a challenge pass for directives, journals, memories, cached
   conclusions, prior project patterns, and stack defaults. Use an independent
   model/counterpart critique when available and include the authorization
   sentence in advisor briefs.
6. Inspect source evidence in order: existing repo docs, package/build config, infra config, CI workflows, environment schemas, deployment docs, secrets documentation, observability/runbooks, PR templates, review rules, branch protection expectations, and existing agent instructions.
7. Decide the technical bootstrap mode:
   - `Connect only`: connect to providers to understand constraints and build local/dev workflow without mutating remote resources.
   - `Local bootstrap`: create local environment docs, scripts, env schema, and dev onboarding without cloud mutations.
   - `CI/review bootstrap`: add or propose quality gates, PR templates, review automation, and branch protections.
   - `Infrastructure bootstrap`: provision or update cloud/deployment resources only after explicit approval.
   - `Legacy reconcile`: import current technology decisions and harden gaps without forcing a new stack.
8. Assess and scaffold the quality system:
   - Local validation: format, lint, typecheck, unit, integration, e2e or smoke tests, build, codegen/schema, migration, seed, and docs checks.
   - CI/CD validation: install/cache, changed-surface checks, full-suite checks, build artifacts, preview/deploy checks, environment validation, migration dry runs, rollback checks, and release promotion gates.
   - PR validation: PR template, required checks, CODEOWNERS or reviewers, branch protection, status naming, high-signal AI review automation, stale/duplicate review prevention, and required evidence in PR bodies.
   - Security validation: dependency audit, license checks, secret scanning, SAST, container or image scans, IaC scans, auth/data boundary tests, environment schema checks, and least-privilege review.
   - Runtime validation: health checks, smoke tests, observability hooks, logging policy, alerting, incident notes, backup/restore checks, and post-deploy verification.
   - AI workstream validation: repo instructions, Claude Code commands, Codex skills, handoff format, review prompts, QA matrix prompts, and framework adoption checks.
9. For each quality layer, mark `present`, `needs update`, `missing`, `not applicable`, or `blocked`, with evidence and the smallest useful scaffold or ticket.
10. Produce a technical foundation package: stack map, repo map, environment contract, secrets contract, quality-gate matrix, CI/CD gates, PR automation, review policy, deployment path, observability path, security/data gates, rollback plan, and AI workstream skills.
11. Produce implementation tickets for missing setup, each sized for one PR or one approved platform action.
12. Validate with available checks: config references, docs links, existing commands, CI syntax when possible, quality gate coverage, and capability truth.
13. Report blocked live actions separately from completed local artifacts.

## Guardrails

- Do not read or print secret values unless explicitly required and approved; prefer secret names, owners, and required scopes.
- Do not mutate cloud resources, CI settings, branch protections, secrets, deployments, or repositories without explicit approval.
- Do not introduce stack choices that conflict with existing source evidence without surfacing the tradeoff.
- Do not create automation that bypasses existing quality gates.
- Do not leave quality gates vague. Name the exact check, owner surface, trigger, blocking behavior, and evidence expected.
- Do not assume every project uses the same cloud, CI provider, issue tracker, language, or AI tool.

## Output

Return a tech terraform result with:

- Bootstrap mode.
- Sources inspected and unavailable.
- Capability and approval gates.
- Stack, repo, environment, quality-gate, CI/CD, PR check, security validation, runtime validation, and AI workstream plan.
- Quality layer matrix with `present`, `needs update`, `missing`, `not applicable`, or `blocked` status.
- Tickets or platform actions created, updated, proposed, or blocked.
- Validation and residual risk.
