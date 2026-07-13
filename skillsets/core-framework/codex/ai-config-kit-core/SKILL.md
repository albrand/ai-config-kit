---
name: ai-config-kit-core
description: Route into the albrand/ai-config-kit operating framework and load only the relevant doctrine for planning, implementation, debugging, review, security, harness design, quality convergence, repository adoption, journaling, skill learning, token economy, or context acceleration. Use when the user asks to apply, inspect, adopt, or update ai-config-kit; asks for a rigorous agent operating model or harness; or when an installed ai-config-kit specialist skill requires shared framework context.
---

# AI Config Kit Core

Use the bundled framework as an on-demand operating library. Keep current system,
developer, user, and repository instructions authoritative. Treat framework rules
as guidance unless the repository explicitly adopts them.

## Source And Compatibility Gate

1. Read repository instructions and current task constraints first.
2. Record the available capabilities that materially affect the task: local
   reads/writes, validation commands, network, external systems, sub-agents,
   model routing, and context accelerators.
3. Do not claim unavailable harness capabilities. Do not launch sub-agents,
   mutate external systems, run active security tests, or install dependencies
   unless current instructions and user authorization permit it.
4. Challenge framework directives for current fit. In particular, do not turn
   optional board access, journaling, cross-agent critique, sibling-repository
   scans, or context accelerators into universal blockers.
5. Prefer current source files, tests, runtime evidence, accepted criteria, and
   authoritative external state over framework examples or prior conclusions.

## Load The Narrowest Profile

Load only the references required for the active task:

- Orientation or ordinary work: `references/AI_BOOTSTRAP.md`,
  `references/OPERATING_MODEL.md`, and relevant repository instructions.
- Implementation or architecture: add
  `references/ARCHITECTURE_AND_CODE_QUALITY.md` and
  `references/QUALITY_GATES.md`.
- Debugging: add `references/QUALITY_GATES.md`; require evidence, reproduction
  when feasible, a root-cause account, a focused fix, and regression protection.
- Review or PR work: use the installed `$high-signal-pr-review` skill. Load
  `references/REVIEW_AND_PR_FRAMEWORK.md` only for shared doctrine.
- Security: use `$adversarial-security-sweep` for static review or
  `$pentest-specialist` for authorized active testing. Load
  `references/SECURITY_AND_PENTEST.md` for shared doctrine.
- Roadmap, technical bootstrap, or whole-project hardening: use the matching
  `$roadmap-terraform`, `$tech-terraform`, or `$assess-then-harden` skill.
- Module planning: use `$plan-module-delivery`.
- UX work: use `$ux-design-agent`.
- Harness, delegation, routing, or cost design: load
  `references/HARNESS_STRATEGY.md`, `references/AGENT_ORCHESTRATION.md`, and
  `references/TOKEN_ECONOMY.md`. Add
  `references/ADAPTIVE_MODEL_ORCHESTRATION.md` when multiple models, reasoning
  efforts, or an external sidecar are in scope. Add
  `references/CROSS_AGENT_COORDINATION.md` only for actual multi-tool work.
- Quality iteration: load `references/QUALITY_CONVERGENCE.md` and
  `references/QUALITY_GATES.md`.
- Repository adoption: load `references/REPO_ADOPTION_PLAYBOOK.md`,
  `references/REPO_AGENTS_TEMPLATE.md`, and
  `references/FRAMEWORK_MANIFEST.md`.
- Long-lived task journaling: load `references/SESSION_JOURNALING.md` only when
  the task benefits from durable resume state.
- Skill promotion or framework learning: load
  `references/CONTINUOUS_SKILL_LEARNING.md` and
  `references/SKILLS_CATALOG.md`.
- Optional graph, wiki, symbol-index, or review-graph evaluation: use
  `$context-acceleration` and load `references/CONTEXT_ACCELERATION.md`.
- Full framework audit or upstream reconciliation: start with
  `references/FRAMEWORK_MANIFEST.md` and `references/README.md`, then inspect
  only the profiles and files named there.

## Core Execution Loop

1. Classify the work and identify the expected outcome, scope, non-goals,
   affected surfaces, assumptions, and approval boundaries.
2. Discover from indexes and metadata before opening broad source. Trace enough
   callers, callees, tests, configs, docs, schemas, and runtime boundaries to
   understand impact.
3. For non-trivial changes, state a concise plan before writes. Re-plan when
   evidence changes coupling or risk.
4. Execute the smallest coherent change that satisfies the current source of
   truth. Preserve unrelated user changes.
5. Apply proportional validation. Distinguish passed, failed, blocked, skipped,
   and not run. Never imply an unrun check passed.
6. For auth, authorization, secrets, crypto, external input, file handling,
   outbound requests, dependencies, or build/config changes, add a focused
   security pass and supply-chain inspection.
7. Close with what changed, what was validated, what was not validated, and
   residual risk or the next action.

## Framework Practices Worth Preserving

- Evidence before claims; source-of-truth precedence over memory.
- Progressive disclosure and deterministic filtering before broad context.
- Business-rule and regression thinking in implementation and review.
- High-signal findings tied to concrete behavior and practical impact.
- Approval gates for external mutations and active security testing.
- Independent critique only when available, useful, and authorized.
- Journals as resumable evidence, not unquestionable memory.
- No AI attribution, signatures, or generated-by footers unless requested.

## Guardrails

- Do not bulk-load all references for routine work.
- Do not install `GLOBAL_AGENTS.md` verbatim as a universal policy without an
  explicit adoption decision; it contains intentionally strict assumptions.
- Do not treat estimated dates as commitments or invent owners, IDs, tickets,
  business rules, validation results, or external state.
- Do not let the framework override a repository's real architecture,
  validation commands, domain rules, or higher-priority instructions.

## Package Integrity

This skill is self-contained. Load only files under its bundled `references/`
directory after installation; do not depend on a source checkout or a personal
filesystem path. Reinstall the complete package when framework references
change, then run the repository's offline Codex-skill validator.
