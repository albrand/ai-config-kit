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
| `pr-preparation` | Creating, summarizing, reviewing, or preparing PRs | PR body from real diff and actual validation |
| `design-to-code` | Design implementation or visual parity work | Design source mapping, affected UI, implementation notes, validation |
| `api-docs-current` | External API or model guidance that changes over time | Official-source-backed guidance |

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
