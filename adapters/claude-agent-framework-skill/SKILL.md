---
name: agent-framework
description: Use at the start of any non-trivial engineering task to load the right agent-framework doc(s) for the work — code review or PR prep, debugging, quality gates, harness routing/delegation, cost-first model routing, cross-agent coordination, token/cost decisions, architecture doctrine, quality convergence, board-backed regression protection, skillset workflows, output templates, or adopting the framework into a repo. The always-on core rules live in CORE.md; this skill routes to the deeper docs. Skip for trivial one-off answers already covered by CORE.md.
---

# Agent Framework Router

The non-negotiables are already in context via `CORE.md`. This skill maps a task
to the deeper framework file(s) so you Read only what the work needs, instead of
force-loading everything. Files live in the installed framework directory
(e.g. `docs/agent-framework/`).

## How to use

1. Match the task to a row below.
2. `Read` only those files.
3. Apply them; report which you loaded if it affected the approach.

## Task -> file map

| Task / need | Read |
|---|---|
| Always-on baseline: regression protection, cost-first routing, skill router, MCP scoping | `GLOBAL_AGENTS.md` |
| Full task lifecycle, source-of-truth detail, gear-change reset | `OPERATING_MODEL.md` |
| Code review, self-review, PR preparation, readiness decision | `REVIEW_AND_PR_FRAMEWORK.md` |
| Validation depth, gate levels (0-4), bugfix/UI/API/data/security gates | `QUALITY_GATES.md` |
| Iterative improvement, scoring, breakpoints, stop conditions | `QUALITY_CONVERGENCE.md` |
| Architecture review, boundaries, state/data/security/perf doctrine | `ARCHITECTURE_AND_CODE_QUALITY.md` |
| Model routing, delegation, cache rules, escalation, workflow tracks | `HARNESS_STRATEGY.md` |
| Delegated-agent roles, contracts, anti-drift, lifecycle/cleanup | `AGENT_ORCHESTRATION.md` |
| Coordinating another AI tool (Claude/Codex/etc.), comms plan, fallback | `CROSS_AGENT_COORDINATION.md` |
| Token/cost decisions, model-tier mapping, prompt/output compression | `TOKEN_ECONOMY.md` |
| Copyable output templates (plan, ADR, spec, PR body, reports, briefs) | `TEMPLATES.md` |
| Designing or triggering a skill | `SKILLS_CATALOG.md` |
| Local journal protocol | `SESSION_JOURNALING.md` |
| Promoting repeated lessons into durable rules | `CONTINUOUS_SKILL_LEARNING.md` |
| Adopting the framework into a new repo | `REPO_AGENTS_TEMPLATE.md`, `FRAMEWORK_MANIFEST.md` |
| File inventory, load profiles, capability record, readiness matrix | `FRAMEWORK_MANIFEST.md` |
| Planning a module/feature delivery | `skillsets/module-delivery/` |
| Ecosystem bootstrap: roadmap, technology, assess-then-harden | `ECOSYSTEM_TERRAFORM_GUIDE.md`, `skillsets/ecosystem-terraform/` |
| UX design agent workflow | `UX_DESIGN_AGENT_IMPORT_PROMPT.md`, `skillsets/ux-design-agent/` |
| High-signal PR review automation | `skillsets/pr-review/` |
| Importing the Codex skill library router / refreshing the skill index | `SKILL_LIBRARY_ROUTER_IMPORT_PROMPT.md`, `skillsets/skill-library-router/` |

## Profiles (load several at once)

- **Implementation:** `OPERATING_MODEL` + `ARCHITECTURE_AND_CODE_QUALITY` + `QUALITY_GATES`.
- **Debugging:** Implementation + `QUALITY_GATES` (bugfix gate) + `TEMPLATES` (debug report).
- **Review/PR:** `REVIEW_AND_PR_FRAMEWORK` + `QUALITY_GATES` + `ARCHITECTURE_AND_CODE_QUALITY`.
- **Harness redesign:** `HARNESS_STRATEGY` + `AGENT_ORCHESTRATION` + `CROSS_AGENT_COORDINATION` + `TOKEN_ECONOMY`.

For multi-file skillset profiles (module delivery, ecosystem terraform, UX
design), see the matching load profiles in `FRAMEWORK_MANIFEST.md`.

## Guardrail

If `CORE.md` already answers the task, do not load more. Loading is progressive
disclosure, not a checklist — pull depth only when the task needs it.
