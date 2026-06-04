# Skills Catalog

Skills are reusable workflows. They should be small, explicit, and easy for agents to apply without rereading old sessions.

Default policy: prefer AI-only skills. Add scripts, validators, or executable helpers only when the team explicitly wants maintained automation.

## Recommended Global Skills

| Skill | Use When | Expected Output |
| --- | --- | --- |
| `analysis-plan-delegate` | Every non-trivial request; also when the prompt says `subagents swarm allowed` | Analysis, plan, context expansion, delegation decision, validation report |
| `harness-routing` | Work that can use model tiers, sub-agents, cache, delegated validation, or the prompt phrase `subagents swarm allowed` | Routing plan, model choice, cache decision, escalation triggers |
| `token-efficiency` | Delegating to sub-agents, choosing model tiers, coordinating another AI, shaping long prompts, or controlling noisy output | Smallest capable tier, compressed brief, output cap, preserved exact evidence |
| `cross-agent-coordination` | Work can benefit from another AI tool acting as peer critic, explorer, executor, verifier, or summarizer; also when the prompt says `subagents swarm allowed` and a counterpart may be useful | Communication plan, counterpart capability gate, output contract, fallback |
| `mcp-routing` | Before using MCPs or external integrations, or when a new registered MCP server appears | Repo/folder/workflow allow-list decision, ask-before-use prompt, external-system fallback |
| `context-reset` | User changes workflow, repo, incident, objective, or the context window is overloaded | Resume packet for previous work and a clean active scope for the new task |
| `instruction-discovery` | Starting repo work or changing directories | Applicable instruction files and scope order |
| `session-journal` | Repo work that needs durable notes | Local action, decision, issue, and validation timeline |
| `systematic-debugging` | Bugs, failing tests, CI failures, deploy failures, env mismatches | Reproducer, root cause or hypothesis, smallest fix, validation |
| `big-change-planning` | Auth, security, architecture, schema, migration, release, infra, broad refactor | Problem, scope, options, recommendation, slices, validation, rollback |
| `verification-before-completion` | Any completed code, docs, config, workflow, or generated artifact change | What changed, what validated it, what was not validated, residual risk |
| `quality-convergence` | High-risk work, repeated validation failures, or user requests for strong confidence | Quality dimensions, target, iterations, evidence, stop reason |
| `framework-readiness` | Installing, auditing, or changing the agent framework | File inventory, load profile, capability record, gaps, next action |
| `skill-library-router` | Codex has a large local skill or plugin library, skill descriptions are shortened or omitted, or a task needs a skill that is explicit-only or not visible in the initial list | Selected skill, generated index status, refreshed counts, missing or stale index state, fallback |
| `pr-preparation` | Creating, summarizing, reviewing, or preparing PRs | PR body from real diff and actual validation |
| `high-signal-pr-review` | Reviewing PRs where false positives are costly | Preflight stop checks, independent issue discovery, validation pass, deduped findings, inline comments only when approved |
| `ux-design-agent` | Figma-first layout, design-system, design-token, component-library, or designer-facing AI workflow work | Capability gate, UX questions with defaults, token/system decision, Figma annotation plan, component-library recommendation, validation |
| `domain-grilling` | Requirements, roadmap, architecture, or tickets contain fuzzy terms or unclear decisions | One-question-at-a-time clarification, recommended answers, glossary updates, ADR candidates |
| `vertical-slice-ticketing` | Turning plans, PRDs, or assessments into executable tickets | One-PR slices with objective, acceptance criteria, validation, dependencies, and resources |
| `issue-triage-state-machine` | Reviewing incoming issues, bugs, feature requests, or tickets for agent readiness | needs-info, ready-for-agent, ready-for-human, wontfix, or equivalent local state with evidence |
| `business-logic-qa` | Deriving QA from tickets, docs, designs, and product requirements | Requirement-to-test matrix, negative paths, permissions, state transitions, owner/status |
| `architecture-deepening` | Legacy hardening, architecture cleanup, or AI navigability improvement | Candidate deepening opportunities, source evidence, testability and locality benefits, decision questions |
| `handoff` | Work crosses agents, sessions, tools, or context windows | Compact resume packet with source evidence, state, blockers, validation, and next step |
| `design-to-code` | Design implementation or visual parity work | Design source mapping, affected UI, implementation notes, validation |
| `api-docs-current` | External API or model guidance that changes over time | Official-source-backed guidance |

## Shared Skillsets

Use shared skillsets when a workflow is broader than one global skill and needs tool-specific entrypoints, shared references, or install instructions.

| Skillset | Use When | Expected Output |
| --- | --- | --- |
| `skillsets/module-delivery/` | A user provides a module, capability area, roadmap item, migration target, or project-planning request and wants evidence-backed phases, tickets, resources, risks, owners, and validation gates | A module scope package, project description, simple phases, PR-sized tickets, resource links, open questions, and a validation report |
| `skillsets/skill-library-router/` | Codex skill-library setup, skill context-budget warnings, plugin-heavy installs, or skill add/update/remove work where every skill should stay accessible when needed | Installed router skill, refreshed local `skill-index.json`, implicit/explicit counts, policy summary, blocked write report |
| `skillsets/ux-design-agent/` | A UX designer, founder, or product team wants a personal Figma-first AI design agent for layouts, design tokens, system conventions, component-library guidance such as shadcn/ui, Figma annotations, or design-to-code handoff | Mode detection, Figma/repo capability gate, UX questions with recommended defaults, token and design-system decision, Figma annotation map, component-library recommendation, artifacts changed or proposed, UX validation |
| `skillsets/ecosystem-terraform/` plus `ECOSYSTEM_TERRAFORM_GUIDE.md` | A user wants `/roadmap-terraform`, `/tech-terraform`, `/assess-then-harden`, project ecosystem bootstrap, roadmap/board reconciliation, technology bootstrap, full quality/CI/CD/PR gate scaffolding, QA matrix creation, or legacy hardening from docs, tickets, designs, repos, cloud, and external sources | Command selection, prompt samples, roadmap or technical operating model, capability gate, questions, source map, artifacts, PR-sized tickets, business-logic QA matrix, quality-gate matrix, approval gates, validation report |
| `skillsets/pr-review/` | A user wants `/code-review`, high-signal PR review, diff review, merge readiness, public review comments, or AI-generated PR review | Preflight decision, scoped instruction map, validated findings, dropped candidates, comment-mode gate, validation reviewed, and residual risk |

Shared skillsets must stay separate from the developer runbook unless their workflow directly changes implementation behavior. Prefer AI-runbook instructions first; add executable helpers only when the team explicitly wants maintained automation.

## Codex Skill Library Indexing

For Codex installs with many skills or plugins, use `skill-library-router` as
the lightweight always-on access layer.

Mandates:

- Install or update the router from `skillsets/skill-library-router/`.
- Keep the router implicit.
- Do not disable skills to save context.
- Treat explicit-only skills as router-accessible and directly invokable by
  `$skill-name`.
- After adding, updating, or removing Codex skills or plugins, run the installed
  `refresh-skill-index.cjs` script and then run it with `--check`.
- Report total skills, implicit skills, explicit-only skills, policy changes,
  and blocked writes before closing the task.

## Imported Engineering Patterns

The framework should incorporate useful public skill patterns as neutral practices, not as private or vendor-locked copies.

- PR review should use high-signal filtering: stop on closed/draft/trivial/already-reviewed PRs, run independent reviewers when available, validate each candidate issue before reporting, dedupe comments, and avoid comments for lint-only or speculative concerns.
- Requirements work should use grilling: ask one material question at a time, propose a recommended answer, inspect source evidence before asking, and capture resolved terminology or irreversible decisions.
- Ticketing should use vertical slices: each ticket should be independently grabbable, demoable or verifiable, and sized for one PR.
- Issue triage should use explicit states: not enough information, ready for an agent, ready for a human, will not do, or the repo's local equivalents.
- Implementation workflows should preserve feedback loops: diagnosis before fixes, red-green-refactor when practical, and validation tied to behavior.
- Architecture hardening should look for shallow modules, scattered concepts, weak test seams, and places where deeper interfaces improve locality and AI navigability.
- Long work should produce compact handoffs instead of carrying raw transcripts forward.

## Repo-Local Skill Examples

Use repo-local skills when a workflow is valuable but not universal.

- `execution-framework`: repo-local sequence for analyze, scan, plan, architect, delegate, integrate, validate.
- `architecture-review`: repo-local architecture, dependency, data-flow, and security review.
- `object-calisthenics`: code quality doctrine for tiny units, low coupling, guard clauses, and explicit names.
- `design-contract-review`: review changed UI against approved designs and runtime contracts.
- `ticket-first-delivery`: issue-tracker workflow for status, acceptance criteria, evidence, and follow-ups.
- `release-readiness`: deployment, rollback, environment, migration, and monitoring readiness.

## Skill Shape

Create each skill as:

```text
<skills-root>/<skill-name>/SKILL.md
```

Recommended content:

```md
---
name: <skill-name>
description: <when this skill must be used>
---

# <Skill Name>

## Trigger

Use this skill when...

## Workflow

1. ...
2. ...
3. ...

## Guardrails

- ...

## Output

Report...
```

## Skill Design Rules

- One skill should cover one recurring workflow.
- Trigger text should be concrete.
- If a skill should translate a user phrase into a runtime routing decision,
  include the exact phrase in the trigger description and define what it
  authorizes, what it does not force, and which safety, privacy, budget, and
  validation checks still apply.
- Workflow steps should be ordered.
- Guardrails should describe what the agent must not do.
- Output requirements should be easy to check.
- Keep examples neutral.
- Avoid private names, URLs, credentials, or closed-scope facts.

## Promotion Rules

Promote repeated behavior to the narrowest useful durable layer:

- Global baseline: applies to all agent work.
- Global skill: repeatable workflow across many repos.
- Parent instruction file: shared convention across a workspace.
- Repo instruction file: architecture or process rule for one repo.
- Repo-local skill: repeated specialized workflow for one repo.
- Automated guard: rule can be checked reliably by lint, tests, CI, or scripts.

## Continuous Learning Loop

After each substantial task, ask:

1. Did the agent repeat a useful workflow?
2. Did the agent miss a rule that should become explicit?
3. Did validation reveal a recurring failure mode?
4. Did a repo-specific convention need a clearer home?
5. Can the lesson be enforced automatically?

If yes, propose one of:

- Add or update a global skill.
- Add or update a repo-local skill.
- Add or update a repo instruction.
- Add a checklist item.
- Add a validation gate.
- Add an automated rule.

Human approval should be required before changing shared skill policy.

When the lesson affects framework installation, adapters, load profiles, or harness capability detection, update `FRAMEWORK_MANIFEST.md` and the relevant adapter or adoption docs in the same change set.

## Anti-Patterns

- Do not put secrets, credentials, sensitive data, or private endpoints in skills.
- Do not copy one repo's architecture into another repo without validating fit.
- Do not add script-backed skills casually.
- Do not create overlapping skills with unclear precedence.
- Do not let skills silently conflict with repo instructions.
