# Framework Manifest

Use this file as the framework inventory, loading guide, and adoption readiness contract.

The manifest does not replace the framework files. It tells an AI agent which files must exist, which files to load for a task, which harness capabilities are available, and what must be verified before claiming the framework is adopted.

## Canonical File Set

Core files:

- `README.md`: overview, layer model, and adoption summary.
- `AI_BOOTSTRAP.md`: first-read instruction for any AI tool.
- `CONFIG_KIT_AI_PROMPT.md`: paste-ready prompt for making any AI absorb the config kit.
- `SKILL_LIBRARY_ROUTER_IMPORT_PROMPT.md`: paste-ready prompt for importing the Codex Skill Library Router and refreshing the local skill index.
- `UX_DESIGN_AGENT_IMPORT_PROMPT.md`: paste-ready prompt for importing the UX Design Agent skillset into Codex and Claude Code.
- `FRAMEWORK_MANIFEST.md`: required file inventory, load profiles, and readiness checks.
- `GLOBAL_AGENTS.md`: global collaboration and execution baseline.
- `OPERATING_MODEL.md`: full task lifecycle and source-of-truth rules.
- `DIRECTIVE_CHALLENGE_AND_CAUSAL_INFERENCE.md`: rationale, examples, and gains
  for challenging directives, memories, journals, cached conclusions, and prior
  patterns as evidence rather than authority.
- `REPO_AGENTS_TEMPLATE.md`: repo-root instruction template.
- `SKILLS_CATALOG.md`: global and repo-local skill design rules.
- `AGENT_ORCHESTRATION.md`: delegated-agent roles, contracts, and cleanup.
- `CROSS_AGENT_COORDINATION.md`: addendum for coordinating multiple AI tools, counterpart capability gates, communication plans, and single-agent fallback.
- `HARNESS_STRATEGY.md`: model routing, cache, validation ownership, and escalation.
- `ADAPTIVE_MODEL_ORCHESTRATION.md`: canonical adoption profiles, capability-first role and effort routing, max/ultra gate, verified example profile, and reconciliation contract.
- `CMUX_HERMES_ORCHESTRATION.md`: bounded, default-off orchestration between cmux (local UI/session transport and lifecycle) and Hermes (provider router, plan/delegation brain, fallback, and usage ledger on a Tailscale-only VPS) via a local deterministic broker; hard network boundary, worktree write isolation, and report-only cleanup.
- `NATIVE_AGENT_SURFACES.md`: capability-first, host-neutral doctrine for discovering and using native host software an agent runs in or through (cmux first adapter; also tmux, zellij, and generic agentic shells/harnesses); never serializes env values or socket capabilities.
- `SECOND_MAC_BOOTSTRAP.md`: git-based second-Mac install from the public repo with explicit copy/install commands; configures its own SSH/Tailscale and never copies credentials.
- `SESSION_JOURNALING.md`: local journal protocol.
- `CONTINUOUS_SKILL_LEARNING.md`: promotion of repeated lessons into durable rules.
- `ARCHITECTURE_AND_CODE_QUALITY.md`: architecture, security, state, data, and quality review doctrine.
- `QUALITY_GATES.md`: validation levels and truth-reporting rules.
- `TEST_OWNERSHIP.md`: ownership- and boundary-based test-evidence decision gate; defers blanket all-changes-need-tests mandates to the smallest falsifiable evidence for the owning surface.
- `SECURITY_AND_PENTEST.md`: authorized defensive-security doctrine — supply-chain hardening, threat modeling, vulnerability lifecycle, multi-pass reinforcement, authorization gate, dual-use guardrails, and security routing.
- `QUALITY_CONVERGENCE.md`: iterative targets, scoring, feedback loops, breakpoints, and stop conditions.
- `REVIEW_AND_PR_FRAMEWORK.md`: review posture and PR evidence requirements.
- `TOKEN_ECONOMY.md`: empirical token-cost recipes (model tier mapping, prompt compression, output filtering, memory hygiene). Complements `HARNESS_STRATEGY.md`.
- `TEMPLATES.md`: copyable output templates.

Support files:

- `CONTEXT_ACCELERATION.md`: optional directives for using a chosen Graphify-compatible knowledge graph/context map or OpenWiki-compatible generated agent wiki as advisory orientation, including the required operator documentation package; not a default dependency or source of truth.
- `AI_TOOL_ADAPTERS.md`: setup guidance for common AI tools.
- `FRAMEWORK_PATTERNS.md`: neutral reusable configuration patterns.
- `INTERNAL_WIKI_PAGE.md`: short paste-ready wiki summary.
- `ECOSYSTEM_TERRAFORM_GUIDE.md`: user-facing guide and prompt samples for roadmap, technology, and hardening bootstrap workflows.
- `skillsets/context-acceleration/`: optional Codex skillset for gating and using selected graph/wiki/symbol/code-review context accelerators at full useful capability.
- `skillsets/adaptive-model-orchestration/`: portable Codex skill, OpenCode/GLM example profile, peer wrappers, package manifest, and offline-install guidance.
- `skillsets/core-framework/`: self-contained explicit-only Codex entrypoint with bundled framework references.
- `skillsets/skill-library-router/`: Codex skillset for indexing large local skill libraries and keeping explicit-only skills discoverable.
- `skillsets/module-delivery/`: standalone AI-runbook skillset for module delivery planning, including Codex and Claude Code entrypoints.
- `skillsets/ux-design-agent/`: Figma-first AI-runbook skillset for UX designers, design tokens, design-system conventions, component-library guidance, and code-aware design handoff.
- `skillsets/ecosystem-terraform/`: executable AI-runbook skillset for roadmap, technology, and hardening bootstrap, including Codex skill mirrors and Claude Code slash commands.
- `skillsets/pr-review/`: executable high-signal PR review skillset, including a Codex skill, Claude Code `/code-review` command, and shared output contract.
- `skillsets/security-review/`: executable defensive-security skillset — the multi-pass `adversarial-security-sweep` (reinforced detection) and the authorization-gated `pentest-specialist`, with Codex skills, Claude Code commands, an output contract, and a supply-chain IoC / CI-guard reference.
- `skillsets/cmux-hermes-orchestration/`: executable, default-off orchestration skillset for cmux (local) + Hermes (remote router on a Tailscale-only VPS), with a stdlib-only deterministic broker, two explicit-only Codex skills (`cmux-hermes-orchestrator`, `plan-arbiter`), Claude Code commands, shared references, durable Hermes work journals, a no-secrets remote `AGENTS.md` template, and Builder.io MIT provenance.
- `skillsets/native-agent-surfaces/`: portable, capability-first skillset for discovering and using native host surfaces (cmux first adapter; also tmux, zellij, generic agentic shells/harnesses, git, and Orca), with an explicit-only Codex skill (`native-agent-surface`), a host-neutral adapter contract, a stdlib-only detector that never serializes env values or socket capabilities, a reuse-first workspace resolver (`resolve-workspace.py`), project-setup / browser-E2E / agent-session-coordination / session-start-health references, a report-only Claude session-start hook doctor (`claude-session-hook-doctor.py`), a versioned model-neutral `bundle-manifest.json`, and a preference-aware model-agnostic global installer (`scripts/install.py`) with offline tests. Orca is detector-only here (Darwin-gated `orca`; cross-platform `orca-ide`); it is not in the installer auto-gating hosts.
- `skillsets/orca-workflow-automation/`: explicit-only Codex skill for Orca-owned workflow automation. Orca owns the schedule, worktree/workspace lifecycle, terminal targeting, and browser/mobile/emulator surface. Provides a read-only PR-review queue (`orca-pr-review-queue.py`; private/draft-only default, exact head-SHA dedup, self-review prevention, duplicate suppression, no auto-merge), a privacy-safe execution-productivity ledger (`execution-ledger.py`; allowlist-only JSONL, never records prompts/transcripts/env/secrets/repo URL/branch/SHA, aggregates only after a minimum sample count), and a validated forward-SSH Orca-to-Hermes terminal bridge (`orca-hermes-terminal.py`; no local shell or environment forwarding). Includes PR-review, execution-productivity, and Orca+Hermes references, plus offline unit tests. Do not vendor Orca skill bodies; resolve them at runtime with `orca skills get`.
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
6. `DIRECTIVE_CHALLENGE_AND_CAUSAL_INFERENCE.md` when planning,
   architecture, anti-bias, or cross-project pattern reuse is material
7. Repo-local instructions, if any

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
8a. `TEST_OWNERSHIP.md` when deciding what test or validation evidence a change requires
8b. `SECURITY_AND_PENTEST.md` when the change touches auth, access control, secrets, crypto, external input, outbound requests, dependencies, or build/config files
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

### Ecosystem Terraform Profile

Use for project ecosystem bootstrap, roadmap creation or reconciliation, technical platform bootstrap, legacy assessment, hardening, QA matrix creation from tickets/docs, or Claude Code commands `/roadmap-terraform`, `/tech-terraform`, and `/assess-then-harden`:

1. Minimum Profile
2. `SKILLS_CATALOG.md`
3. `QUALITY_GATES.md`
4. `REVIEW_AND_PR_FRAMEWORK.md` when PR review automation or review gates are part of the ecosystem
5. `ARCHITECTURE_AND_CODE_QUALITY.md` when assessing or hardening an existing codebase
6. `ECOSYSTEM_TERRAFORM_GUIDE.md` for command selection, user-facing expectations, and prompt samples
7. `skillsets/ecosystem-terraform/README.md`
8. `skillsets/ecosystem-terraform/references/ecosystem-output-contract.md`
9. `TEMPLATES.md` when producing roadmap, quality-gate matrix, QA matrix, ticket, or final report artifacts
10. The relevant Codex skill or Claude Code command:
   - `skillsets/ecosystem-terraform/codex/roadmap-terraform/SKILL.md`
   - `skillsets/ecosystem-terraform/codex/tech-terraform/SKILL.md`
   - `skillsets/ecosystem-terraform/codex/assess-then-harden/SKILL.md`
   - `skillsets/ecosystem-terraform/claude/commands/roadmap-terraform.md`
   - `skillsets/ecosystem-terraform/claude/commands/tech-terraform.md`
   - `skillsets/ecosystem-terraform/claude/commands/assess-then-harden.md`
11. External source evidence required by the request: docs, repos, boards, designs, PRs, deployments, cloud accounts, QA artifacts, and stakeholder instructions

### UX Design Agent Profile

Use for Figma-first UX design workflows, layout creation, product UI shaping, design-system setup, design-token creation or import, component-library guidance, Figma annotation workflows, code-aware design handoff, or the Claude Code command `/ux-design-agent`:

1. Minimum Profile
2. `SKILLS_CATALOG.md`
3. `QUALITY_GATES.md`
4. `ARCHITECTURE_AND_CODE_QUALITY.md` when repo tokens, component architecture, or implementation handoff are in scope
5. `AI_TOOL_ADAPTERS.md` when installing Codex or Claude entrypoints
6. `skillsets/ux-design-agent/README.md`
7. `skillsets/ux-design-agent/references/output-contract.md`
8. The relevant Codex skill or Claude Code command:
   - `skillsets/ux-design-agent/codex/ux-design-agent/SKILL.md`
   - `skillsets/ux-design-agent/claude/commands/ux-design-agent.md`
9. External source evidence required by the request: Figma files, Figma libraries, brand guidelines, screenshots, repos, component docs, tokens, Storybook, accessibility requirements, product docs, and design-tool access

### Skill Library Router Profile

Use for Codex skill library setup, skill context-budget warnings, plugin-heavy installs, skill add/update/remove work, or smart access to explicit-only skills:

1. Minimum Profile
2. `SKILLS_CATALOG.md`
3. `AI_TOOL_ADAPTERS.md` when installing the Codex entrypoint
4. `SKILL_LIBRARY_ROUTER_IMPORT_PROMPT.md` when importing or updating the router
5. `skillsets/skill-library-router/README.md`
6. `skillsets/skill-library-router/codex/skill-library-router/SKILL.md`
7. `skillsets/skill-library-router/codex/skill-library-router/scripts/refresh-skill-index.cjs`
8. Current Codex skill/plugin inventory, generated index status, and any sandbox permission blockers

### Debugging Profile

Use for bugs, failing tests, CI failures, deploy failures, environment mismatches, or unexpected behavior:

1. Implementation Profile
2. `QUALITY_GATES.md`
3. `TEMPLATES.md` debugging and validation reports
4. Any repo-specific logs, reproduction steps, contracts, or environment docs

### Security Review Profile

Use for security review, hardening, vulnerability discovery, threat modeling,
supply-chain/dependency risk, or the Claude Code commands
`/adversarial-security-sweep` and `/pentest-specialist`:

1. Minimum Profile
2. `SECURITY_AND_PENTEST.md`
3. `QUALITY_GATES.md` Security Gate
4. `HARNESS_STRATEGY.md` security routing tier when delegating lens work
5. `skillsets/security-review/README.md`
6. `skillsets/security-review/references/security-review-contract.md`
7. `skillsets/security-review/references/supply-chain-iocs.md`
8. The relevant Codex skill or Claude Code command:
   - `skillsets/security-review/codex/adversarial-security-sweep/SKILL.md`
   - `skillsets/security-review/codex/pentest-specialist/SKILL.md`
   - `skillsets/security-review/claude/commands/adversarial-security-sweep.md`
   - `skillsets/security-review/claude/commands/pentest-specialist.md`
9. The owned or authorized target evidence: repo, diff, dependencies, configs,
   and authorization basis for any active testing

### cmux + Hermes Orchestration Profile

Use when an operator has adopted cmux as the local UI/session surface and Hermes
as the remote provider router (Tailscale-only VPS), and wants bounded,
one-writer-per-task delegation, persistent master sessions, exact usage, or
plan arbitration:

1. Minimum Profile
2. `CMUX_HERMES_ORCHESTRATION.md`
3. `AGENT_ORCHESTRATION.md` for delegated-agent roles and contracts
4. `ADAPTIVE_MODEL_ORCHESTRATION.md` when model-tier/effort routing is in scope
5. `QUALITY_GATES.md` validation and security gates
6. `skillsets/cmux-hermes-orchestration/README.md`
7. `skillsets/cmux-hermes-orchestration/references/HERMES_PROTOCOL.md`
8. `skillsets/cmux-hermes-orchestration/references/CMUX_SURFACES.md`
9. `skillsets/cmux-hermes-orchestration/references/WORKTREE_OWNERSHIP.md`
10. `skillsets/cmux-hermes-orchestration/references/BUILDERIO_PROVENANCE.md`
11. The relevant Codex skill or Claude Code command:
    - `skillsets/cmux-hermes-orchestration/codex/cmux-hermes-orchestrator/SKILL.md`
    - `skillsets/cmux-hermes-orchestration/codex/plan-arbiter/SKILL.md`
    - `skillsets/cmux-hermes-orchestration/claude/commands/cmux-hermes.md`
    - `skillsets/cmux-hermes-orchestration/claude/commands/plan-arbiter.md`
12. The broker CLI:
    `skillsets/cmux-hermes-orchestration/codex/cmux-hermes-orchestrator/scripts/cmux-hermes.py`
13. Evidence required by the step: repo path, base branch, target alias,
    live provider/model catalog, Tailscale/SSH reachability, and explicit
    per-task delegation activation

### Review And PR Profile

Use for code review, self-review, PR preparation, or readiness decisions:

1. Minimum Profile
2. `REVIEW_AND_PR_FRAMEWORK.md`
3. `QUALITY_GATES.md`
4. `ARCHITECTURE_AND_CODE_QUALITY.md`
5. `skillsets/pr-review/README.md` and `skillsets/pr-review/references/pr-review-output-contract.md` when performing high-signal PR review or posted review workflows
6. Actual diff, changed files, app-value details, and linked ticket if applicable

The PR review output contract is mandatory for public review comments,
merge-readiness comments, and PR bodies. It controls inline thread shape,
root-cause commentary, practical failure examples, safe suggestion blocks,
minimal PR body shape, transcript-free PR surfaces, and no AI attribution.

### Adoption Profile

Use when installing the framework into a new repo or another AI tool:

1. `README.md`
2. `FRAMEWORK_MANIFEST.md`
3. `AI_BOOTSTRAP.md`
4. `CONFIG_KIT_AI_PROMPT.md`
5. `SKILL_LIBRARY_ROUTER_IMPORT_PROMPT.md` when importing the Codex Skill Library Router or adopting Codex with a large skill library
6. `UX_DESIGN_AGENT_IMPORT_PROMPT.md` when importing the UX Design Agent skillset into Codex or Claude Code
7. `AI_TOOL_ADAPTERS.md`
8. `REPO_ADOPTION_PLAYBOOK.md`
9. `REPO_AGENTS_TEMPLATE.md`
10. `DIRECTIVE_CHALLENGE_AND_CAUSAL_INFERENCE.md`
11. `TEMPLATES.md`
12. The adapter file for the target AI tool

### Harness Redesign Profile

Use when changing model routing, cache rules, delegated-agent policy, validation ownership, or escalation behavior:

1. Implementation Profile
2. `AGENT_ORCHESTRATION.md`
3. `CROSS_AGENT_COORDINATION.md`
4. `HARNESS_STRATEGY.md`
5. `ADAPTIVE_MODEL_ORCHESTRATION.md` when multiple models, effort levels, or a sidecar are in scope
6. `OPENCODE_DELEGATION.md` when OpenCode participates
7. `TOKEN_ECONOMY.md`
8. `QUALITY_GATES.md`
9. `CONTINUOUS_SKILL_LEARNING.md`

### Adaptive Model Orchestration Profile

Use when adopting or operating adaptive/always-on cross-family routing,
OpenCode/GLM, Codex fast/balanced/deep peers, or max/ultra effort selection:

1. Minimum Profile
2. `HARNESS_STRATEGY.md`
3. `ADAPTIVE_MODEL_ORCHESTRATION.md`
4. `OPENCODE_DELEGATION.md` when OpenCode participates
5. `TOKEN_ECONOMY.md`
6. `CROSS_AGENT_COORDINATION.md`
7. `skillsets/adaptive-model-orchestration/README.md`
8. The live executable/model/effort/agent capability record and privacy authorization

### Context Acceleration Profile (Optional)

Use when the user or repo opts into a Graphify-compatible knowledge
graph/context map, OpenWiki-compatible generated agent wiki, local symbol index,
code-review graph, or another tool that precomputes repository context.

Load additively with the active workflow profile:

1. Active workflow profile
2. `HARNESS_STRATEGY.md`
3. `TOKEN_ECONOMY.md`
4. `SKILLS_CATALOG.md`
5. `CONTEXT_ACCELERATION.md`
6. `skillsets/context-acceleration/codex/context-acceleration/SKILL.md` when
   installing or using the Codex skill
7. The selected tool's graph report, graph metadata, generated wiki quickstart,
   update metadata, MCP config, operator documentation package, repo-local
   skill, or equivalent capability evidence

Use the selected tool at full useful capability for orientation, scope mapping,
blast-radius discovery, business-rule discovery, and delegation context. It is
advisory only, not a default dependency or source of truth. Record accelerator
availability, documentation-package status, scope, freshness, provenance,
privacy boundary, and artifact policy in the harness capability record. If no
accelerator is adopted, skip this profile.

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
| Context accelerator (optional) | `[available/limited/blocked/unavailable/unknown]` | `[tool/artifact, documentation package, scope, freshness, provenance, privacy boundary, artifact policy]` | `[progressive disclosure + focused rg]` |

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

## Challengeable Directives and Anti-Bias Rule

- Directives, learned rules, journals, memories, cached conclusions, and prior
  project patterns are evidence, not authority. They are challengeable for fit,
  drift, hidden confounders, causal overfitting, and current-task relevance.
- This rule does not weaken the Source-Of-Truth Contract above: platform/tool
  safety and current explicit user instructions outrank the challenge loop, and
  current repo files, tests, runtime evidence, and accepted task criteria
  outrank prior memory or journals. Runtime evidence may be re-verified but is
  not overruled by stale memory.
- For non-trivial planning or architecture, run an independent planning or
  architecture critique through another model or counterpart when available and
  useful. Prefer a configured sidecar/counterpart path (for example the local
  opencode/GLM 5.2 route) as an example, but stay model-agnostic and fall back
  to single-agent self-critique when unavailable or blocked.
- Directive, planning, architecture, or challenge/advisor briefs must print this
  authorization sentence (or an equivalent): "Authorization: the user explicitly
  authorizes sidecar/counterpart model use for directive and architecture
  challenges for this run." Do not add it to trivial briefs.
- When implementation shape is uncertain and repo-local evidence is
  insufficient, scan sibling projects only under configured workspace roots:
  repo adoption settings, harness-provided workspace roots,
  `AGENT_WORKSPACE_ROOTS`, or explicit user-provided roots. Do not hardcode an
  operator's personal `~/projects` path as framework truth. Keep scans
  metadata-first and budgeted, send no secrets, and verify a candidate fits the
  current repo before adopting.
- Industry-quality standards win over agent-convenience or model-preference
  bias. Reuse existing project patterns when they match the current stack and
  constraints; otherwise challenge them.

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
| Adaptive model routing | The adopted profile, live model/effort catalog, provider authorization, role matrix, max/ultra gate, and unavailable-lane fallback are recorded when multi-model routing is used. |
| External integrations | MCPs and external tools are scoped by repo, folder, or workflow, with ask-before-use behavior for unrecorded connections. |
| Context acceleration (optional) | If the team adopts a graph or wiki accelerator, availability, operator documentation package, freshness, provenance, privacy boundary, artifact policy, opt-in state, and advisory boundary are recorded per `CONTEXT_ACCELERATION.md`. |
| Journaling | The repo states whether journals are required, optional, local-only, versioned, or disabled. |
| Quality gates | Required focused, lint, typecheck, test, build, security, and release checks are listed. |
| Quality convergence | Iteration targets, max iterations, stop conditions, and escalation rules are defined for high-risk work. |
| Skills | Global and repo-local skills are listed only where they have clear triggers. Codex skill libraries with many skills or plugins have a generated router index or an explicit blocker. |
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
- Skill index check: when Codex skills or plugins changed, run the installed
  `skill-library-router` refresh command and `--check`, or report the exact
  sandbox or permission blocker.
- Codex package check: run `node scripts/validate-codex-skills.cjs`; verify
  frontmatter limits, bundled references, package manifests, and executable
  modes without requiring provider credentials.
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
