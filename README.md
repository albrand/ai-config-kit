# Agent Configuration Framework

This repository is a shareable, tool-neutral operating framework for AI coding agents.

It tells an AI assistant how to discover instructions, analyze before acting, plan before editing, route work through available harness capabilities, coordinate with other AI tools when available, use delegated agents safely, keep work resumable, enforce quality gates, and report validation truth.

The kit is intentionally generic. Do not add secrets, private URLs, non-public repository names, internal roadmap facts, credentials, private account identifiers, or domain-specific operating details to the shared files.

## What This Repository Is

Use this repository as a portable instruction kit for AI-assisted software work.

It provides:

- A universal bootstrap contract any AI tool can read.
- A manifest that lists required files, load profiles, harness capabilities, and readiness checks.
- Global agent behavior that can be installed at user or workspace level.
- Repo-level instruction templates for local architecture, validation, and workflow rules.
- Tool adapters for AGENTS-compatible tools, Claude Code, Gemini CLI, Cursor, and generic chat assistants.
- A harness model for master-thread ownership, delegated-agent routing, cache decisions, validation, and escalation.
- A cross-agent coordination addendum for tool-neutral paired work where one AI coordinates another AI, peer reviewer, or external executor.
- Quality gates for docs, code, UI, API, data, security, deployment, and review work.
- A quality convergence loop for work that needs measured improvement across iterations.
- Session journaling guidance for resumable local work.
- Continuous skill learning guidance so repeated lessons become durable rules, skills, or automated gates.
- Templates for plans, routing records, readiness reports, debugging reports, validation reports, PR bodies, and delegation briefs.

It is not:

- A package with a runtime build.
- A replacement for repo-specific architecture rules.
- A place to store private delivery workflows or sensitive operational data.
- A guarantee that every AI tool supports sub-agents, model routing, cache, shell access, validation execution, or access to a second AI membership.

## Quick Start

### Use The Kit In This Repository

The framework files live at the repository root.

For any substantial change to this kit, read:

1. `CONFIG_KIT_AI_PROMPT.md`
2. `AI_BOOTSTRAP.md`
3. `FRAMEWORK_MANIFEST.md`
4. `GLOBAL_AGENTS.md`
5. `OPERATING_MODEL.md`
6. The task-relevant files listed in the manifest load profiles

Then follow the docs-only validation gate in `QUALITY_GATES.md`.

### Use The Kit In Another Repository

Recommended installed layout:

```text
<target-repo>/
  AGENTS.md
  docs/
    agent-framework/
      AI_BOOTSTRAP.md
      FRAMEWORK_MANIFEST.md
      GLOBAL_AGENTS.md
      OPERATING_MODEL.md
      ...
```

Adoption sequence:

1. Copy the framework files into a stable path, usually `docs/agent-framework/`.
2. Copy the relevant adapter from `adapters/` into the target repo or AI tool settings.
3. Copy `REPO_AGENTS_TEMPLATE.md` into the repo instruction file and replace placeholders.
4. Record the real harness capabilities for the active AI tool.
5. Define local source-of-truth order, architecture boundaries, validation commands, journaling policy, and release rules.
6. Run the first-session verification prompt from `CONFIG_KIT_AI_PROMPT.md` or `TEMPLATES.md`.
7. Run a low-risk trial task and check that the AI follows the local rules.

### Use The Kit In A Chat-Only AI Tool

Use this path when the AI cannot read files from a repository:

1. Paste `CONFIG_KIT_AI_PROMPT.md`.
2. Attach or paste `AI_BOOTSTRAP.md`.
3. Attach or paste `FRAMEWORK_MANIFEST.md`.
4. Attach or paste `GLOBAL_AGENTS.md` and `OPERATING_MODEL.md`.
5. Add only the task-relevant files, such as `QUALITY_GATES.md`, `REVIEW_AND_PR_FRAMEWORK.md`, or `HARNESS_STRATEGY.md`.
6. Ask the AI to report missing files, active source-of-truth order, capability gaps, breakpoints, validation plan, and smallest safe next step before implementation.

Use `adapters/GENERIC_AI_PROMPT.md` only as a short fallback when the full ingestion prompt is too large.

## Core Mental Model

The framework separates instructions by scope.

Apply layers from broad to narrow:

1. Platform and tool safety rules.
2. User-level global instructions.
3. Global skills.
4. Parent directory instructions.
5. Repo-root instructions.
6. Repo-local skills and process docs.
7. Current prompt.

When layers conflict:

- Platform and safety rules win.
- Current user instructions can narrow the task.
- Repo-local rules control repo architecture, validation, release, data, security, and workflow details.
- Global framework files provide defaults.
- If a conflict affects behavior, security, data handling, validation, release, or scope, ask before implementing.

The active AI thread should act as the master owner of:

- User intent.
- Source-of-truth order.
- Architecture and ambiguity decisions.
- Task decomposition.
- Delegated-agent contracts.
- Cross-agent communication plans when a second AI tool participates.
- Integration.
- Final validation truth.
- Delivery report.

Delegated agents, smaller models, cache, and validation executors are optional harness capabilities. Use them only when the active tool actually supports them and the output can be reviewed.

In Codex environments with model routing, `gpt-5.3-codex-spark` is the default
bounded worker/explorer tier for low-risk quick or standard subtasks. Route the
first safe bounded sidecar to Spark when useful and cheap to validate; keep
architecture, security, data-loss risk, production release gates, ambiguous
debugging, broad refactors, and final review verdicts in the master thread or
strongest available reasoning path.

External integrations are also scoped capabilities. Before using MCPs or other
external tools, confirm they are enabled for the current repo, folder, or
workflow. Ask before using unrecorded or newly registered MCP servers, and keep
local repository truth above external convenience when code behavior is the
question.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `README.md` | Entry point, quick-start guide, file map, usage recipes, and maintenance overview. |
| `CONFIG_KIT_AI_PROMPT.md` | Paste-ready prompt that tells any AI how to absorb this kit from files, pasted content, a folder, or an archive. |
| `AI_BOOTSTRAP.md` | First-read instruction for any AI tool; short enough for custom instructions or project rules. |
| `FRAMEWORK_MANIFEST.md` | Canonical file inventory, load profiles, harness capability record, source-of-truth contract, readiness matrix, and maintenance checks. |
| `GLOBAL_AGENTS.md` | Global collaboration and execution baseline for agent behavior. |
| `OPERATING_MODEL.md` | Full lifecycle for intake, discovery, planning, routing, implementation, integration, self-review, validation, and close-out. |
| `REPO_AGENTS_TEMPLATE.md` | Repo-root instruction template with placeholders for local rules. |
| `AI_TOOL_ADAPTERS.md` | Setup guide for generic assistants, AGENTS-compatible tools, Cursor, Gemini CLI, Claude Code, Codex, and other tools. |
| `adapters/` | Copyable bootstrap files for specific AI tools. |
| `SKILLS_CATALOG.md` | Recommended global skills, repo-local skill examples, skill shape, promotion rules, and anti-patterns. |
| `AGENT_ORCHESTRATION.md` | Delegation rules, agent roles, ownership boundaries, routing rules, integration checklist, and anti-patterns. |
| `CROSS_AGENT_COORDINATION.md` | Addendum for coordinating multiple AI tools with capability gates, communication plans, output contracts, and single-agent fallback. |
| `HARNESS_STRATEGY.md` | Master/sub-agent routing, model tiers, cache rules, anti-drift rules, escalation, validation, and delivery standards. |
| `SESSION_JOURNALING.md` | Local execution journal protocol for resumable repository work. |
| `CONTINUOUS_SKILL_LEARNING.md` | Promotion ladder for turning repeated lessons into rules, skills, templates, or automated gates. |
| `ARCHITECTURE_AND_CODE_QUALITY.md` | Generic architecture review, boundary principles, code quality doctrine, state/data/security/performance review, and self-review checklist. |
| `QUALITY_GATES.md` | Validation levels, evidence rules, docs/code/UI/API/data/security/release gates, and validation report template. |
| `QUALITY_CONVERGENCE.md` | Controlled iteration loop with dimensions, targets, scoring, breakpoints, evidence packets, and stop conditions. |
| `REVIEW_AND_PR_FRAMEWORK.md` | Review posture, criteria, finding format, self-review, PR preparation, approval standard, and PR body template. |
| `FRAMEWORK_PATTERNS.md` | Neutral reusable patterns for collaboration, source-of-truth order, impact mapping, debugging, big changes, review, journaling, validation, skills, routing, and convergence. |
| `TEMPLATES.md` | Copyable templates for plans, routing, capability records, readiness reports, convergence, debugging, validation, completion, review findings, PRs, skills, and delegation. |
| `REPO_ADOPTION_PLAYBOOK.md` | Step-by-step adoption guide for installing the framework into a repo. |
| `INTERNAL_WIKI_PAGE.md` | Short paste-ready wiki summary for teams that want an internal documentation page. |

## Load Profiles

Use the smallest profile that covers the task. Load a broader profile when the work becomes more complex or the source-of-truth surface expands.

### Minimum Profile

Use for short answers, first-session checks, and paste-only mode:

1. `CONFIG_KIT_AI_PROMPT.md` when available
2. `AI_BOOTSTRAP.md`
3. `FRAMEWORK_MANIFEST.md`
4. `GLOBAL_AGENTS.md`
5. `OPERATING_MODEL.md`
6. Repo-local instructions, if any

### Implementation Profile

Use for code, docs, config, workflow, or generated-artifact changes:

1. Minimum profile
2. `REPO_AGENTS_TEMPLATE.md` or the adopted repo instruction file
3. `SKILLS_CATALOG.md`
4. `AGENT_ORCHESTRATION.md`
5. `CROSS_AGENT_COORDINATION.md` when another AI tool, external agent, or peer reviewer may participate
6. `HARNESS_STRATEGY.md`
7. `ARCHITECTURE_AND_CODE_QUALITY.md`
8. `QUALITY_GATES.md`
9. `QUALITY_CONVERGENCE.md` when quality targets require iteration
10. `TOKEN_ECONOMY.md` when delegation, cross-agent coordination, prompt compression, or cost control matters
11. `TEMPLATES.md` when a structured plan or report is useful
12. `SESSION_JOURNALING.md` if the repo uses journals

### Debugging Profile

Use for bugs, failing tests, CI failures, deployment failures, environment mismatches, and unexpected runtime behavior:

1. Implementation profile
2. `QUALITY_GATES.md`
3. Debugging and validation templates from `TEMPLATES.md`
4. Repo-specific logs, reproduction steps, contracts, environment docs, and runtime evidence

### Review And PR Profile

Use for code review, self-review, PR preparation, and readiness decisions:

1. Minimum profile
2. `REVIEW_AND_PR_FRAMEWORK.md`
3. `QUALITY_GATES.md`
4. `ARCHITECTURE_AND_CODE_QUALITY.md`
5. Actual diff, changed files, validation output, and repo PR template

### Adoption Profile

Use when installing the framework into a new repository or AI tool:

1. `README.md`
2. `FRAMEWORK_MANIFEST.md`
3. `AI_BOOTSTRAP.md`
4. `CONFIG_KIT_AI_PROMPT.md`
5. `AI_TOOL_ADAPTERS.md`
6. `REPO_ADOPTION_PLAYBOOK.md`
7. `REPO_AGENTS_TEMPLATE.md`
8. `TEMPLATES.md`
9. The adapter file for the target AI tool

### Harness Redesign Profile

Use when changing model routing, cache rules, delegated-agent policy, validation ownership, or escalation behavior:

1. Implementation profile
2. `AGENT_ORCHESTRATION.md`
3. `CROSS_AGENT_COORDINATION.md`
4. `HARNESS_STRATEGY.md`
5. `TOKEN_ECONOMY.md`
6. `QUALITY_GATES.md`
7. `CONTINUOUS_SKILL_LEARNING.md`

## Tool Adapters

Adapters should be short bootstrap files. They should point to the framework, not fork the whole framework into every tool-specific file.

| Tool or mode | Recommended file | Where to put it |
| --- | --- | --- |
| AGENTS-compatible tools | `adapters/AGENTS.md` | Target repo root as `AGENTS.md` |
| Codex-style repo instructions | `adapters/AGENTS.md` | Target repo root as `AGENTS.md` |
| Claude Code | `adapters/CLAUDE.md` | Target repo root as `CLAUDE.md` |
| Gemini CLI | `adapters/GEMINI.md` | Target repo root as `GEMINI.md` |
| Cursor | `adapters/cursor-agent-framework.mdc` | Target repo `.cursor/rules/agent-framework.mdc` |
| Generic chat assistant | `CONFIG_KIT_AI_PROMPT.md` | Paste into chat before attaching files |
| Generic short fallback | `adapters/GENERIC_AI_PROMPT.md` | Paste only when the full prompt is too large |

Important adapter rule:

- The adapters use `docs/agent-framework/` as the recommended installed framework path.
- If your target repo uses a different path, update the adapter imports before adoption.
- Replace all repo-specific placeholders before treating a repo as adopted.

## Harness Capability Record

Before substantial work, the AI should record what the active tool can actually do.

Capability statuses:

- `available`: supported and usable now.
- `limited`: supported with constraints that affect routing.
- `blocked`: normally supported but unavailable in this session.
- `unavailable`: not supported by the tool.
- `unknown`: not yet verified.

Capabilities to record:

- File read access.
- File edit access.
- Shell or command execution.
- Validation execution.
- Sub-agents or delegation.
- Cross-agent counterpart access.
- Model routing.
- Cache or memory.
- MCP or external integration routing.
- Network or external tools.
- Browser or UI verification.
- Persistent journals.

Fallback rule:

- If sub-agents, cross-agent counterpart access, model routing, cache, browser verification, or shell execution are unavailable, keep the same lifecycle locally.
- Do not pretend a blocked capability exists.
- Report the limitation in the plan and close-out.

Codex Spark rule:

- When Codex model routing is available, route the first safe bounded sidecar
  for quick or standard work to `gpt-5.3-codex-spark` when useful.
- Before using a stronger Codex tier for delegated work, explicitly ask whether
  Spark can safely handle the bounded task.
- Spark delegates should stop on scope expansion, conflicting requirements,
  repeated validation failure, missing source-of-truth context, or security and
  data concerns.

Codex concurrency and freshness rule:

- When Codex exposes a configurable thread ceiling, prefer:

  ```toml
  max_concurrent_threads_per_session = 16
  ```

- Treat completed, stale, or prior-workflow subagents as consumed context:
  capture any needed output or resume packet, close them when the tool permits,
  and open fresh agents for new delegated work.

Swarm phrase contract:

- If the live user prompt includes the exact phrase `subagents swarm allowed`,
  treat it as explicit authorization and request wording for sub-agents,
  parallel delegation, model routing, and cross-agent counterpart routing for
  that prompt or thread.
- The phrase enables routing when useful and supported. It does not bypass
  capability checks, privacy filtering, budget/output caps, stop conditions,
  anti-drift rules, validation, or the single-agent fallback.

MCP and external integration rule:

- Prefer local repo truth for code behavior. Use MCPs and external integrations
  when the external system owns the answer or when the user explicitly asks for
  that system.
- Keep MCPs scoped by repo, folder, or workflow. On first folder-level use, ask
  which registered connections are enabled. If a new MCP server appears, ask
  where it should be enabled before using it.
- If Replit OAuth returns `invalid_scope` or generates an auth URL without
  scopes, rerun `codex mcp login --scopes openid,profile,email replit` and use
  the fresh URL.

Gear-change rule:

- When the user switches workflow, repo, incident, or objective, stop carrying
  the previous workflow as active context. Leave a compact resume packet when
  useful, then reload only the relevant instructions, source files, external
  systems, and validation requirements for the new objective.

## Standard Workflow

For normal repository work:

1. Intake.
   - Identify the objective, task type, explicit constraints, hidden assumptions, expected output, and workflow track.
2. Discovery.
   - Locate instructions, load the manifest, inspect repository state, read task-relevant source-of-truth docs, and map the affected surface.
3. Planning.
   - State objective, scope, non-goals, impacted surface, approach, validation, rollback or fallback, breakpoints, and stop conditions.
4. Harness routing.
   - Decide what stays local, what can be delegated, whether another AI tool should participate, what model tier is appropriate, whether cache is safe, and what validation each unit must produce.
5. Implementation or analysis.
   - Keep changes scoped, preserve repo boundaries, and ask when controlling sources conflict.
6. Integration.
   - Review local and delegated work, remove drift, keep unrelated changes intact, and align naming and boundaries.
7. Self-review.
   - Compare the output to the request, source-of-truth docs, architecture boundaries, and validation plan.
8. Validation.
   - Run focused checks first, then broader checks when risk or repo rules require them.
9. Close-out.
   - Report changed surface, validation, skipped or blocked checks, residual risk, and next required step.

## Workflow Tracks

Use the track to scale depth:

| Track | Use when | Expected discipline |
| --- | --- | --- |
| `quick` | Clear bug, small feature, narrow docs/config change | Short plan, narrow inspection, focused validation. |
| `standard` | Normal implementation or docs work | Full impacted-surface mapping, implementation profile, focused plus relevant broad validation. |
| `big-change` | Architecture, security, data, migration, release, broad refactor | Options, recommendation, slices, breakpoints, rollback, broad validation. |
| `recovery` | Failing tests, CI, deploy, environment, runtime incident | Reproducer, evidence-backed hypotheses, smallest fix, re-run reproducer and regression check. |
| `review` | PR, diff, design, readiness review | Findings first, severity order, source-of-truth comparison, validation review, residual risk. |

Small-looking tasks can become `big-change` if they touch security, data, auth, release, or shared architecture.

## Delegation And Routing

Use delegated agents or smaller models only when the work is separable, supported by the active tool, and reviewable.

When another AI tool is available, treat it as a counterpart capability rather than a mandatory dependency. The coordinator may use the counterpart as a peer critic, explorer, bounded executor, verifier, or summarizer, but must first create a communication plan: coordinator and counterpart roles, source-of-truth package, work split, output contract, budget, stop conditions, and single-agent fallback.

Delegate when:

- Independent questions can be answered in parallel.
- Implementation slices have disjoint write scopes.
- A side investigation can run while the main path continues.
- Parallel validation can catch concrete risk.

Keep work local when:

- The next step is blocked on the result.
- The task is small or tightly coupled.
- The subtask requires nuanced judgment that would be expensive to specify.
- Delegation would duplicate work already underway.

Every delegated task needs:

- Role.
- Bounded objective.
- Owned files or modules.
- Explicit non-goals.
- Required context.
- Allowed outputs.
- Success criteria.
- Validation expectations.
- Escalation conditions.
- Coordination warning that the worker must not revert unrelated edits.

The master thread must review delegated output before relying on it.

Cross-agent work should produce better results than either tool alone. If the counterpart is unauthenticated, rate-limited, unavailable, too expensive, or not useful for the task, keep the same lifecycle in the coordinator and report the capability gap instead of lowering validation standards.

## Quality Gates

Quality gates prove the requested outcome, not just general repo health.

Always distinguish:

- Passed.
- Failed.
- Blocked.
- Skipped.
- Not run.

Docs-only changes should use Level 0 from `QUALITY_GATES.md`:

- Reference scan.
- Manifest inventory check when framework files change.
- Closed-scope scan.
- Markdown formatting or lint when available.
- ASCII or encoding check when required.
- Archive check when maintaining a distributable bundle.

Code changes should add focused tests, lint, typecheck, relevant broader tests, build, security checks, data checks, or release checks according to risk.

Never report unrun checks as passed.

## Quality Convergence

Use quality convergence when one pass is not enough.

Use it for:

- Complex implementation work.
- High-risk refactors.
- Security, data, auth, release, or architecture changes.
- Repeated validation failures.
- Review follow-ups where the first patch is insufficient.
- User requests for high confidence, durable quality, strong tests, or exhaustive cleanup.

The loop:

```text
DEFINE TARGETS -> IMPLEMENT -> MEASURE -> SCORE -> FEEDBACK -> ITERATE -> FINAL REVIEW
```

Each iteration should produce:

- Artifact.
- Evidence.
- Feedback for the next iteration.

Stop when:

- Target quality is met.
- Remaining gaps need a user decision.
- Validation is blocked.
- The same failure repeats without new evidence.
- Quality plateaus.
- A fix would expand scope beyond the request.

## Session Journaling

Use journals when the target repository adopts journaling or when work needs durable local notes.

Recommended journal path:

```text
journals/
```

Record:

- Source-of-truth docs read.
- Important files inspected.
- Commands and outcomes.
- Decisions and rejected alternatives.
- Files changed.
- Validation results.
- Blockers and residual risk.
- Next exact resume step.

Do not record secrets, credentials, sensitive values, large command dumps, or private URLs unless local policy explicitly allows them.

## Continuous Skill Learning

Promote repeated behavior to the narrowest durable layer where future agents will use it.

Promotion ladder:

1. Final response for one-time observations.
2. Session journal for task-local resumability.
3. Framework manifest for file inventory, load profiles, readiness, and capability records.
4. Repo instruction file for repo architecture, validation, release, and workflow rules.
5. Repo-local skill for repeated workflows in one repo.
6. Parent instruction file for workspace conventions.
7. Global skill for repeatable workflows across many repos.
8. Global instruction file for universal behavior.
9. Automated gate when the rule can be reliably checked.

Human approval should be required before changing shared skill policy.

## Adoption Walkthrough

Follow `REPO_ADOPTION_PLAYBOOK.md` for the full process.

Summary:

1. Inventory the target repo.
   - Find existing agent files, contributor docs, architecture docs, testing docs, release docs, issue workflows, CI, validation commands, and fragile areas.
2. Choose local layers.
   - Decide which bootstrap, manifest, adapter, repo instruction, skills, journals, and automated gates the repo will use.
3. Create repo instructions.
   - Copy `REPO_AGENTS_TEMPLATE.md` or an adapter and replace placeholders.
4. Add journaling if needed.
   - Decide local-only versus versioned and document the lifecycle.
5. Define quality gates.
   - List focused, lint, typecheck, test, build, security, generated artifact, and release checks.
6. Add repo-local skills only where needed.
   - Keep triggers concrete and avoid overlap with global skills.
7. Run first-session verification.
   - Confirm the AI sees the right layers, files, capabilities, validation commands, and conflict rules.
8. Run a trial task.
   - Check planning, context expansion, scope control, validation truth, and journal use.
9. Maintain.
   - Remove stale rules, promote repeated lessons, keep validation current, and keep closed-scope details local.

Adoption is complete only when a fresh AI session can summarize the active instruction layers, capability map, validation requirements, journaling policy, and conflict rules without editing files.

## First-Session Verification Prompt

Use this after installing or attaching the kit:

```text
Absorb the Agent Configuration Framework from the provided config kit.

Do not edit files yet.

Report:
1. Which framework files you loaded.
2. Which required framework files are missing.
3. Which repo-local instruction file controls this repository, if any.
4. The active source-of-truth order.
5. Your harness capability map.
6. Required validation commands or gaps.
7. Whether journaling is required.
8. Which quality convergence triggers apply.
9. Any conflicts or blockers before implementation.
10. The smallest safe next step.
```

## Common Recipes

### Plan A Normal Implementation

Load:

- Minimum profile.
- `ARCHITECTURE_AND_CODE_QUALITY.md`.
- `QUALITY_GATES.md`.
- `TEMPLATES.md`.

Then produce:

- Objective.
- Scope and non-goals.
- Impacted surface.
- Approach.
- Validation.
- Rollback or fallback.

### Debug A Failure

Load:

- Debugging profile.
- Reproducer, logs, payloads, failing command output, environment docs, and relevant source files.

Then:

1. Capture the exact symptom.
2. Reproduce when feasible.
3. State expected versus actual behavior.
4. Form one to three evidence-backed hypotheses.
5. Test the cheapest discriminating hypothesis first.
6. Patch only after root cause is supported.
7. Re-run the reproducer and one nearby regression check.

### Review A PR Or Diff

Load:

- Review and PR profile.
- Actual diff.
- Changed files.
- Source-of-truth docs.
- Relevant tests and validation output.

Output:

- Findings first, ordered by severity.
- File and line references where possible.
- Open questions.
- Validation reviewed.
- Residual risk.

### Prepare A PR Body

Use `REVIEW_AND_PR_FRAMEWORK.md` and the PR template in `TEMPLATES.md`.

Base the PR body on:

- Real diff.
- Changed files.
- Actual validation.
- Deployment or operational impact.
- Rollback path.
- Residual risk.

Do not leave template sections blank. Use `N/A` when a section does not apply.

### Install A Tool Adapter

1. Choose the adapter from `AI_TOOL_ADAPTERS.md`.
2. Copy the adapter to the target tool path.
3. Update framework imports to match the target repo path.
4. Replace placeholders.
5. Run the first-session verification prompt.

### Create Or Update A Skill

Use:

- `SKILLS_CATALOG.md`.
- `CONTINUOUS_SKILL_LEARNING.md`.
- Skill template from `TEMPLATES.md`.

Keep skills:

- Concrete.
- Small.
- Trigger-based.
- Ordered.
- Free of closed-scope details.
- Non-overlapping with existing skills.

## Maintenance

After changing this framework, run the strongest practical docs-only checks.

Recommended checks:

```text
rg --files
rg -n "docs/agent-framework|AI_BOOTSTRAP.md|FRAMEWORK_MANIFEST.md|CONFIG_KIT_AI_PROMPT.md" .
git diff --check
```

Also check:

- Required files listed in `FRAMEWORK_MANIFEST.md` still exist.
- Adapter paths are accurate for the documented install layout.
- Shared files do not contain secrets, private URLs, private account identifiers, or repo-specific facts.
- Markdown remains readable.
- Placeholder text is intentional in templates and adapters.
- Any distributable archive is rebuilt if it is being used.

## Distribution

The tracked repository is the source of truth.

When distributing the framework:

1. Prefer copying the tracked files directly.
2. If using an archive, build it from the current working tree.
3. Include the root framework files and `adapters/`.
4. Exclude `.git/`, local journals, temporary files, credentials, and private overlays.
5. After creating an archive, list its contents and verify it includes the current README and manifest.

`FRAMEWORK_MANIFEST.md` references `config-kit.zip` as the conventional distributable archive name. Some older checkouts track `Archive.zip`. Treat archives as generated distribution output unless your repo intentionally tracks one, and do not leave the active archive stale after framework changes.

## Shareability And Security Checklist

Before publishing, copying, or attaching this kit:

- [ ] No secrets or credentials.
- [ ] No private URLs.
- [ ] No private account identifiers.
- [ ] No non-public repository names.
- [ ] No internal roadmap or delivery facts.
- [ ] No organization-specific domain examples.
- [ ] Placeholder text remains only where a target repo must fill local details.
- [ ] Adapters point to the correct framework path for the target repo.
- [ ] The manifest file inventory matches the files being distributed.
- [ ] The receiving AI can report loaded files and missing capability gaps.

## Troubleshooting

### The AI Starts Coding Before Loading The Kit

Paste `CONFIG_KIT_AI_PROMPT.md` first and ask the AI to report loaded files, missing files, capability map, quality gates, and the smallest safe next step before implementation.

### The AI Cannot Read Repository Files

Use paste mode:

1. Paste `CONFIG_KIT_AI_PROMPT.md`.
2. Paste `AI_BOOTSTRAP.md`.
3. Paste `FRAMEWORK_MANIFEST.md`.
4. Paste only the task-relevant files.

### The AI Claims It Can Delegate But The Tool Cannot

Require a harness capability record. If delegation is unavailable, the AI should keep the same lifecycle locally and report the limitation.

### Adapter Imports Point To Missing Paths

The adapters assume `docs/agent-framework/` in the target repo. Update imports when the framework lives somewhere else.

### A Repo Instruction Conflicts With The Framework

Repo-local rules control local architecture, validation, data, security, release, and workflow details. Ask a direct question before implementing if the conflict changes behavior, scope, security, data handling, validation, or release.

### The README And Manifest Disagree

Treat `FRAMEWORK_MANIFEST.md` as the inventory and readiness contract. Update the README and manifest together when file inventory, load profiles, or adoption readiness rules change.

## Glossary

| Term | Meaning |
| --- | --- |
| Agent framework | This full set of shared instruction, routing, validation, and adoption files. |
| Bootstrap | The first instructions an AI reads before substantial work. |
| Manifest | The file inventory, load profile, capability record, and readiness contract. |
| Adapter | A short tool-specific file that points an AI tool at the shared framework. |
| Harness | The active tool environment and routing layer around the AI: files, shell, validation, sub-agents, models, cache, external tools, browser checks, and journals. |
| Master thread | The main AI conversation that owns user intent, architecture, escalation, integration, and final validation truth. |
| Delegated agent | A bounded helper agent or model assigned a narrow read-only, implementation, or validation task. |
| Quality gate | A validation requirement tied to the work type and risk level. |
| Quality convergence | A measured iteration loop for raising work quality with evidence. |
| Closed-scope detail | Sensitive, private, domain-specific, or organization-specific information that does not belong in the shared framework. |

## Minimal Bootstrap Text

When space is limited, use:

```text
Read CONFIG_KIT_AI_PROMPT.md if available. Then read AI_BOOTSTRAP.md and FRAMEWORK_MANIFEST.md first. Load the framework files relevant to the task. If you cannot access them, ask for them before substantial implementation. Analyze before acting, plan before editing, map the impacted surface, verify available harness capabilities, preserve repo-local rules over generic defaults, validate before completion, and report passed, failed, blocked, skipped, and not-run checks separately.
```
