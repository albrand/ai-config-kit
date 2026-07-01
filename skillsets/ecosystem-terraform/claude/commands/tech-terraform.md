---
description: Bootstrap or reconcile the technical platform, local environments, CI/CD gates, PR automation, infrastructure, and AI developer workstreams.
argument-hint: [stack prompt, repo paths, infra/cloud target, CI/CD and quality requirements]
---

# Tech Terraform

Use this command to create or reconcile the technical operating system for a project. This is a Claude Code runbook command, not a custom script. Use normal Claude Code capabilities and connected MCP/CLI systems only after verifying access and approval. Assess the existing implementation and scaffold or propose every useful quality gate, validation, CI/CD check, PR check, and developer workflow guard for the stack and risk profile.

User input:

`$ARGUMENTS`

Before mutating cloud resources, repositories, CI settings, branch protections, secrets, deployment projects, or tracker items, verify the required capability and ask for approval. Before launching sub-agents, parallel agents, or a swarm, ask whether the user approves that routing for this run.

## Workflow

1. Load `ECOSYSTEM_TERRAFORM_GUIDE.md` and `skillsets/ecosystem-terraform/references/ecosystem-output-contract.md` if available.
2. Extract target stacks, existing repos, legacy constraints, cloud/provider preferences, runtime environments, deployment model, CI/CD requirements, PR review expectations, agent tooling, compliance needs, and desired write scope.
3. Verify required channels: repo write access, GitHub, package manager, cloud CLI/MCP, deployment MCP/CLI, secret manager, CI provider, docs/design systems, and sub-agent availability.
4. Ask up to three targeted questions when missing answers affect stack choice, infrastructure authority, secret handling, environment shape, quality gates, or automation behavior. Include swarm/parallel approval if useful.
5. Present a short execution plan before writes: discovery, capability gaps, stack assumptions, artifacts, quality layers to assess, validation, rollback/fallback, and approval gates.
   Challenge directives, journals, memories, cached conclusions, prior project patterns, and stack defaults as evidence, not authority; use an independent model/counterpart critique when available and include the authorization sentence in advisor briefs.
6. Inspect existing repo docs, package/build config, infra config, CI workflows, env schemas, deployment docs, secrets documentation, observability/runbooks, PR templates, review rules, branch protection expectations, and agent instructions.
7. Choose bootstrap mode: connect only, local bootstrap, CI/review bootstrap, infrastructure bootstrap, or legacy reconcile.
8. Assess and scaffold the full quality system:
   - Local validation: format, lint, typecheck, unit, integration, e2e or smoke tests, build, codegen/schema, migration, seed, and docs checks.
   - CI/CD validation: install/cache, changed-surface checks, full-suite checks, build artifacts, preview/deploy checks, environment validation, migration dry runs, rollback checks, and release promotion gates.
   - PR validation: PR template, required checks, CODEOWNERS or reviewers, branch protection, status naming, high-signal AI review automation, stale/duplicate review prevention, and required evidence in PR bodies.
   - Security validation: dependency audit, license checks, secret scanning, SAST, container or image scans, IaC scans, auth/data boundary tests, environment schema checks, and least-privilege review.
   - Runtime validation: health checks, smoke tests, observability hooks, logging policy, alerting, incident notes, backup/restore checks, and post-deploy verification.
   - AI workstream validation: repo instructions, Claude Code commands, Codex skills, handoff format, review prompts, QA matrix prompts, and framework adoption checks.
9. For each quality layer, mark `present`, `needs update`, `missing`, `not applicable`, or `blocked`, with evidence and the smallest useful scaffold or ticket.
10. Produce the technical foundation package: stack map, repo map, environment contract, secrets contract, quality-gate matrix, CI/CD gates, PR automation, review policy, deployment path, observability path, security/data gates, rollback plan, and AI workstream skills.
11. Produce implementation tickets for missing setup, each sized for one PR or one approved platform action.
12. Validate with available checks and report blocked live actions separately from completed local artifacts.

## Output

Use the final report shape from `ecosystem-output-contract.md`. Include the quality layer matrix and approval gates remaining before cloud mutation, repo creation, CI mutation, branch protection changes, secret handling, or sub-agent swarm.
