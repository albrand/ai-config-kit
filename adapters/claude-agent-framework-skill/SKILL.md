---
name: agent-framework
description: Use at the start of any non-trivial engineering task to load the right agent-framework doc(s) for the work — code review or PR prep, security review, pentest, hardening, threat modeling, supply-chain/dependency risk, debugging, quality gates, test-evidence ownership, harness routing/delegation, cost-first model routing, OpenCode sidecar handoff, sibling-project pattern scans under configured workspace roots, directive-challenge/causal-inference guard, cross-agent coordination, context acceleration with an adopted graph/wiki/symbol index, token/cost decisions, architecture doctrine, quality convergence, board-backed regression protection, skillset workflows, output templates, or adopting the framework into a repo. The always-on core rules live in CORE.md; this skill routes to the deeper docs. Skip for trivial one-off answers already covered by CORE.md.
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
| Challenging directives/memory/patterns as evidence, avoiding causal overfitting | `DIRECTIVE_CHALLENGE_AND_CAUSAL_INFERENCE.md` |
| Reusing a sibling-project pattern; keeping the scan metadata-first and limited to configured workspace roots (`AGENT_WORKSPACE_ROOTS`, adoption settings, explicit user input) | `DIRECTIVE_CHALLENGE_AND_CAUSAL_INFERENCE.md`; `REPO_ADOPTION_PLAYBOOK.md` to configure the roots |
| Delegating to an OpenCode sidecar: handoff contract, capability gate, modes, effort/max-ultra routing | `ADAPTIVE_MODEL_ORCHESTRATION.md`, `OPENCODE_DELEGATION.md` |
| Code review, self-review, PR preparation, readiness decision | `REVIEW_AND_PR_FRAMEWORK.md` |
| Security review, hardening, vulnerability discovery, threat modeling, supply-chain/dependency risk, `/adversarial-security-sweep`, `/pentest-specialist` | `SECURITY_AND_PENTEST.md`, `skillsets/security-review/README.md`, `skillsets/security-review/references/security-review-contract.md`, `skillsets/security-review/references/supply-chain-iocs.md`. Active testing requires the authorization gate in `SECURITY_AND_PENTEST.md` — do not run it from the generic quality-gate path. |
| Validation depth, gate levels (0-4), bugfix/UI/API/data/security gates | `QUALITY_GATES.md` |
| Deciding what test or validation evidence a change actually owes | `TEST_OWNERSHIP.md` |
| Iterative improvement, scoring, breakpoints, stop conditions | `QUALITY_CONVERGENCE.md` |
| Architecture review, boundaries, state/data/security/perf doctrine | `ARCHITECTURE_AND_CODE_QUALITY.md` |
| Model routing, delegation, cache rules, escalation, workflow tracks | `HARNESS_STRATEGY.md` |
| Delegated-agent roles, contracts, anti-drift, lifecycle/cleanup | `AGENT_ORCHESTRATION.md` |
| Coordinating another AI tool (Claude/Codex/etc.), comms plan, fallback | `CROSS_AGENT_COORDINATION.md` |
| Token/cost decisions, model-tier mapping, prompt/output compression | `TOKEN_ECONOMY.md` |
| Copyable output templates (plan, ADR, spec, PR body, reports, briefs) | `TEMPLATES.md` |
| Designing or triggering a skill | `SKILLS_CATALOG.md` |
| Reusable, tool-neutral configuration patterns | `FRAMEWORK_PATTERNS.md` |
| Using an adopted context accelerator (knowledge graph, generated agent wiki, symbol index, code-review graph) | `CONTEXT_ACCELERATION.md`, `skillsets/context-acceleration/README.md`, plus the repo-local operator documentation package. Verify freshness, scope, privacy boundary, and artifact policy; treat generated claims as advisory until primary sources confirm them. |
| Local journal protocol | `SESSION_JOURNALING.md` |
| Promoting repeated lessons into durable rules | `CONTINUOUS_SKILL_LEARNING.md` |
| Adopting the framework into a new repo | `AI_BOOTSTRAP.md`, `REPO_ADOPTION_PLAYBOOK.md`, `REPO_AGENTS_TEMPLATE.md`, `FRAMEWORK_MANIFEST.md` |
| Installing the kit into another AI tool (Cursor, Gemini CLI, Codex, chat-only) | `AI_TOOL_ADAPTERS.md`, `adapters/`, `CONFIG_KIT_AI_PROMPT.md` for paste-only tools |
| Writing an internal team wiki page about the framework | `INTERNAL_WIKI_PAGE.md` |
| File inventory, load profiles, capability record, readiness matrix | `FRAMEWORK_MANIFEST.md` |
| Planning a module/feature delivery | `skillsets/module-delivery/` |
| Ecosystem bootstrap: roadmap, technology, assess-then-harden | `ECOSYSTEM_TERRAFORM_GUIDE.md`, `skillsets/ecosystem-terraform/` |
| UX design agent workflow | `UX_DESIGN_AGENT_IMPORT_PROMPT.md`, `skillsets/ux-design-agent/` |
| High-signal PR review automation | `skillsets/pr-review/` |
| Importing the Codex skill library router / refreshing the skill index | `SKILL_LIBRARY_ROUTER_IMPORT_PROMPT.md`, `skillsets/skill-library-router/` |
| Adaptive/always-on cross-family routing, effort selection, max/ultra gate | `ADAPTIVE_MODEL_ORCHESTRATION.md`, `skillsets/adaptive-model-orchestration/` |
| cmux (local) + Hermes (remote router) bounded orchestration | `CMUX_HERMES_ORCHESTRATION.md`, `skillsets/cmux-hermes-orchestration/` |
| Discovering/using native host surfaces (cmux, tmux, zellij, agentic shells); reuse-first workspace resolution | `NATIVE_AGENT_SURFACES.md`, `skillsets/native-agent-surfaces/` |
| Isolated Orca browser work and ownership-safe tab cleanup | `skillsets/orca-browser-safety/` |
| Installing the kit on another machine from the public repo | `SECOND_MAC_BOOTSTRAP.md` |
| Self-contained Codex entrypoint with bundled framework references | `skillsets/core-framework/` |

## Profiles (load several at once)

- **Implementation:** `OPERATING_MODEL` + `ARCHITECTURE_AND_CODE_QUALITY` + `QUALITY_GATES`.
- **Debugging:** Implementation + `QUALITY_GATES` (bugfix gate) + `TEMPLATES` (debug report).
- **Review/PR:** `REVIEW_AND_PR_FRAMEWORK` + `QUALITY_GATES` + `ARCHITECTURE_AND_CODE_QUALITY`.
- **Security review:** `SECURITY_AND_PENTEST` + `QUALITY_GATES` (Security Gate) + `HARNESS_STRATEGY` security routing tier when delegating lens work + `skillsets/security-review/README.md` + `skillsets/security-review/references/security-review-contract.md` + `skillsets/security-review/references/supply-chain-iocs.md`. Active testing also needs the authorization basis for the target.
- **Context acceleration:** the active workflow profile + `CONTEXT_ACCELERATION.md` + `skillsets/context-acceleration/README.md` + the repo-local operator documentation package.
- **Harness redesign:** `HARNESS_STRATEGY` + `AGENT_ORCHESTRATION` + `CROSS_AGENT_COORDINATION` + `TOKEN_ECONOMY`.

For multi-file skillset profiles (module delivery, ecosystem terraform, UX
design), see the matching load profiles in `FRAMEWORK_MANIFEST.md`.

## Guardrail

If `CORE.md` already answers the task, do not load more. Loading is progressive
disclosure, not a checklist — pull depth only when the task needs it.
