# Framework Manifest

Use this file as the framework inventory, loading guide, and adoption readiness contract.

The manifest does not replace the framework files. It tells an AI agent which files must exist, which files to load for a task, which harness capabilities are available, and what must be verified before claiming the framework is adopted.

## Canonical File Set

Core files:

- `README.md`: overview, layer model, and adoption summary.
- `AI_BOOTSTRAP.md`: first-read instruction for any AI tool.
- `CONFIG_KIT_AI_PROMPT.md`: paste-ready prompt for making any AI absorb the config kit.
- `FRAMEWORK_MANIFEST.md`: required file inventory, load profiles, and readiness checks.
- `GLOBAL_AGENTS.md`: global collaboration and execution baseline.
- `OPERATING_MODEL.md`: full task lifecycle and source-of-truth rules.
- `REPO_AGENTS_TEMPLATE.md`: repo-root instruction template.
- `SKILLS_CATALOG.md`: global and repo-local skill design rules.
- `AGENT_ORCHESTRATION.md`: delegated-agent roles, contracts, and cleanup.
- `CROSS_AGENT_COORDINATION.md`: addendum for coordinating multiple AI tools, counterpart capability gates, communication plans, and single-agent fallback.
- `HARNESS_STRATEGY.md`: model routing, cache, validation ownership, and escalation.
- `SESSION_JOURNALING.md`: local journal protocol.
- `CONTINUOUS_SKILL_LEARNING.md`: promotion of repeated lessons into durable rules.
- `ARCHITECTURE_AND_CODE_QUALITY.md`: architecture, security, state, data, and quality review doctrine.
- `QUALITY_GATES.md`: validation levels and truth-reporting rules.
- `QUALITY_CONVERGENCE.md`: iterative targets, scoring, feedback loops, breakpoints, and stop conditions.
- `REVIEW_AND_PR_FRAMEWORK.md`: review posture and PR evidence requirements.
- `TOKEN_ECONOMY.md`: empirical token-cost recipes (model tier mapping, prompt compression, output filtering, memory hygiene). Complements `HARNESS_STRATEGY.md`.
- `TEMPLATES.md`: copyable output templates.

Support files:

- `AI_TOOL_ADAPTERS.md`: setup guidance for common AI tools.
- `FRAMEWORK_PATTERNS.md`: neutral reusable configuration patterns.
- `INTERNAL_WIKI_PAGE.md`: short paste-ready wiki summary.
- `skillsets/module-delivery/`: standalone AI-runbook skillset for module delivery planning, including Codex and Claude Code entrypoints.
- `adapters/`: tool-specific bootstrap files that point at the framework.
- `config-kit.zip` or `Archive.zip`: distributable archive. `config-kit.zip` is
  the conventional name; `Archive.zip` is a legacy tracked name in some
  checkouts. Rebuild the active archive after framework changes, and do not
  leave a tracked distributable stale.

## Load Profiles

Use the smallest profile that covers the task. When in doubt, load the next broader profile.

### Minimum Profile

Use for short answers, paste-only mode, or first-session checks:

1. `CONFIG_KIT_AI_PROMPT.md` when available
2. `AI_BOOTSTRAP.md`
3. `FRAMEWORK_MANIFEST.md`
4. `GLOBAL_AGENTS.md`
5. `OPERATING_MODEL.md`
6. Repo-local instructions, if any

### Implementation Profile

Use for code, docs, config, workflow, or generated-artifact changes:

1. Minimum Profile
2. `REPO_AGENTS_TEMPLATE.md` or the adopted repo instruction file
3. `SKILLS_CATALOG.md`
4. `AGENT_ORCHESTRATION.md`
5. `CROSS_AGENT_COORDINATION.md` when another AI tool, external agent, or peer reviewer may participate
6. `HARNESS_STRATEGY.md`
7. `ARCHITECTURE_AND_CODE_QUALITY.md`
8. `QUALITY_GATES.md`
9. `QUALITY_CONVERGENCE.md` when quality targets require iteration
10. `TOKEN_ECONOMY.md` when delegating, designing sub-agent prompts, coordinating another AI tool, or evaluating cost
11. `TEMPLATES.md` when a structured plan or report is useful
12. `SESSION_JOURNALING.md` if the repo uses journals

### Module Delivery Planning Profile

Use for module-roadmap, project-planning, milestone, ticket-shaping, or migration-planning work:

1. Minimum Profile
2. `SKILLS_CATALOG.md`
3. `skillsets/module-delivery/README.md`
4. `skillsets/module-delivery/references/output-contract.md`
5. `skillsets/module-delivery/codex/SKILL.md` when installing or using the Codex skill
6. `skillsets/module-delivery/claude/commands/plan-module-delivery.md` when installing or using the Claude Code slash command
7. Board, repository, design, PR, and external-source evidence required by the module request

### Debugging Profile

Use for bugs, failing tests, CI failures, deploy failures, environment mismatches, or unexpected behavior:

1. Implementation Profile
2. `QUALITY_GATES.md`
3. `TEMPLATES.md` debugging and validation reports
4. Any repo-specific logs, reproduction steps, contracts, or environment docs

### Review And PR Profile

Use for code review, self-review, PR preparation, or readiness decisions:

1. Minimum Profile
2. `REVIEW_AND_PR_FRAMEWORK.md`
3. `QUALITY_GATES.md`
4. `ARCHITECTURE_AND_CODE_QUALITY.md`
5. Actual diff, changed files, validation output, and repo PR template

### Adoption Profile

Use when installing the framework into a new repo or another AI tool:

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

1. Implementation Profile
2. `AGENT_ORCHESTRATION.md`
3. `CROSS_AGENT_COORDINATION.md`
4. `HARNESS_STRATEGY.md`
5. `TOKEN_ECONOMY.md`
6. `QUALITY_GATES.md`
7. `CONTINUOUS_SKILL_LEARNING.md`

## Harness Capability Record

Before substantial work, record the actual capabilities available in the active tool. Do not assume a capability exists because the framework mentions it.

Use these values:

- `available`: supported and usable now.
- `limited`: supported with constraints that affect routing.
- `blocked`: normally supported but unavailable in this session.
- `unavailable`: not supported by the tool.
- `unknown`: not yet verified.

Required fields:

| Capability | Status | Evidence | Fallback |
| --- | --- | --- | --- |
| File read access | `[available/limited/blocked/unavailable/unknown]` | `[how verified]` | `[what to do if missing]` |
| File edit access | `[available/limited/blocked/unavailable/unknown]` | `[how verified]` | `[what to do if missing]` |
| Shell or command execution | `[available/limited/blocked/unavailable/unknown]` | `[how verified]` | `[what to do if missing]` |
| Validation execution | `[available/limited/blocked/unavailable/unknown]` | `[how verified]` | `[what to do if missing]` |
| Sub-agents or delegation | `[available/limited/blocked/unavailable/unknown]` | `[how verified]` | `[local decomposition path]` |
| Cross-agent counterpart access | `[available/limited/blocked/unavailable/unknown]` | `[tool/auth/capture evidence]` | `[single-agent path]` |
| Model routing | `[available/limited/blocked/unavailable/unknown]` | `[how verified]` | `[single-model path]` |
| Cache or memory | `[available/limited/blocked/unavailable/unknown]` | `[how verified]` | `[fresh inspection path]` |
| MCP or external integration routing | `[available/limited/blocked/unavailable/unknown]` | `[folder/workflow allow-list evidence]` | `[local-only or ask-before-use path]` |
| Network or external tools | `[available/limited/blocked/unavailable/unknown]` | `[how verified]` | `[local-only path]` |
| Browser or UI verification | `[available/limited/blocked/unavailable/unknown]` | `[how verified]` | `[alternate verification]` |
| Persistent journals | `[available/limited/blocked/unavailable/unknown]` | `[how verified]` | `[manual notes or disabled]` |

Fallback rule:

- If sub-agents, cross-agent counterpart access, model routing, MCP routing, or cache are unavailable, keep the same lifecycle locally: decompose, execute small slices, validate, self-review, and report capability gaps.
- If Codex sub-agents are available and the environment exposes a configurable
  thread ceiling, record whether `max_concurrent_threads_per_session = 16` or a
  stricter local value is active.
- When sub-agents are used, verify the lifecycle rule: capture needed output
  from completed, stale, or prior-workflow agents, close them when the tool
  permits, and spawn fresh agents for new delegated work.

## Source-Of-Truth Contract

Apply sources from highest authority to local detail:

1. Platform, safety, and tool rules.
2. Current user request.
3. Repo-local instruction files and accepted task criteria.
4. Current source files, tests, generated artifacts, runtime contracts, logs, and payloads.
5. Global framework files.
6. Prior memory, journals, or cached conclusions.

Rules:

- Current executable evidence beats older memory.
- Repo-local architecture and validation rules beat generic examples.
- The current user request can narrow scope, but it should not silently override safety, security, data handling, or validation requirements.
- If two controlling sources conflict in a way that affects behavior, scope, security, data, validation, or release, ask before implementing.

## Adoption Readiness Matrix

A repo or AI tool has adopted the framework only when each required item is true or explicitly marked not applicable.

| Area | Required Evidence |
| --- | --- |
| File inventory | Required framework files are present at the documented path. |
| Adapter path | The AI tool can find `CONFIG_KIT_AI_PROMPT.md`, `AI_BOOTSTRAP.md`, and `FRAMEWORK_MANIFEST.md`. |
| Repo instructions | The repo has an adopted instruction file with placeholders replaced. |
| Source-of-truth order | Local instructions state which docs, issues, runtime contracts, and code conventions control. |
| Harness capabilities | Capabilities are recorded as available, limited, blocked, unavailable, or unknown. |
| Cross-agent coordination | Counterpart access is recorded, and paired work has a communication plan plus single-agent fallback. |
| External integrations | MCPs and external tools are scoped by repo, folder, or workflow, with ask-before-use behavior for unrecorded connections. |
| Journaling | The repo states whether journals are required, optional, local-only, versioned, or disabled. |
| Quality gates | Required focused, lint, typecheck, test, build, security, and release checks are listed. |
| Quality convergence | Iteration targets, max iterations, stop conditions, and escalation rules are defined for high-risk work. |
| Skills | Global and repo-local skills are listed only where they have clear triggers. |
| Closed-scope boundary | Shared files contain no secrets, private URLs, private account identifiers, or repo-specific facts. |
| First-session check | A fresh AI session can summarize loaded layers, capabilities, validation commands, and conflict rules. |
| Distribution | The shared archive or copied bundle includes the current files. |

## Maturity Levels

Use these levels to describe adoption honestly:

- `Starter`: the AI can read `AI_BOOTSTRAP.md`, but local repo rules or validation commands are incomplete.
- `Usable`: the repo has local instructions, validation commands, and a working adapter.
- `Harnessed`: the repo records capabilities, routes work through available harness features, and has truthful validation reporting.
- `Durable`: recurring lessons are promoted to skills, repo rules, or automated gates; journals or equivalent resumability are defined.
- `Verified`: a fresh AI session passes the first-session check and a low-risk trial task without missing required layers.

## Framework Maintenance Checks

Run these after changing the kit:

- File inventory check: confirm every required file exists.
- Reference check: confirm docs do not point at missing files.
- Closed-scope scan: search for secrets, private URLs, private account identifiers, and repo-specific facts.
- Placeholder check: shared templates may contain placeholders, adopted local files should not.
- Encoding check: keep shared files plain ASCII unless a file has a documented reason for Unicode.
- Subagent lifecycle check: confirm Codex or compatible installs set an
  appropriate thread ceiling such as `max_concurrent_threads_per_session = 16`
  and close completed, stale, or prior-workflow agents before opening fresh
  delegated contexts.
- Archive check: rebuild and list `config-kit.zip` when it is the active
  distributable. If the checkout still tracks `Archive.zip`, refresh or replace
  it deliberately and verify that the archive contains current framework files.

## Readiness Report Template

```md
Framework readiness:
- Maturity level: <Starter|Usable|Harnessed|Durable|Verified>
- Files present: <passed/failed and gaps>
- Adapter path: <tool and path>
- Harness capabilities: <available/limited/blocked/unavailable/unknown summary>
- Cross-agent counterpart: <available/limited/blocked/unavailable/not useful and fallback>
- Journaling: <required/optional/disabled and path>
- Required validation: <commands or "not defined">
- Closed-scope scan: <passed/failed/not run>
- First-session check: <passed/failed/not run>
- Archive updated: <yes/no/not applicable>

Gaps:
- <gap or "None identified">

Next action:
- <smallest useful next step>
```
