# AGENTS.md

This repository uses the Agent Configuration Framework.

## Bootstrap

Read repository instructions and the current request first. For substantial
work, load `docs/agent-framework/AI_BOOTSTRAP.md`,
`docs/agent-framework/FRAMEWORK_MANIFEST.md`, and
`docs/agent-framework/OPERATING_MODEL.md`. Load the narrowest task skill and its
required references as needed; do not bulk-load every framework profile.

Carry existing authorization, finish the requested outcome, fix known in-scope
defects, and continue independent work while another step awaits input. Apply
hard prohibitions and actual repository release requirements. Use board evidence
when configured or material to the requested conclusion; do not invent board
prerequisites for local maintenance. A generic skill approval step does not
invalidate authorization already given in the current conversation.

Also read any repo-specific source-of-truth docs listed below.

For ecosystem bootstrap workflows such as `/roadmap-terraform`,
`/tech-terraform`, or `/assess-then-harden`, also read
`docs/agent-framework/ECOSYSTEM_TERRAFORM_GUIDE.md` plus the relevant
`docs/agent-framework/skillsets/ecosystem-terraform/` files.

For high-signal PR review, diff review, merge readiness, or `/code-review`,
also read `docs/agent-framework/skillsets/pr-review/` files and follow
`docs/agent-framework/skillsets/pr-review/references/pr-review-output-contract.md`
as the mandatory public review and PR-body contract.

For security review, hardening, vulnerability discovery, threat modeling,
supply-chain/dependency risk, or `/adversarial-security-sweep` and
`/pentest-specialist`, also read `docs/agent-framework/SECURITY_AND_PENTEST.md`
and `docs/agent-framework/skillsets/security-review/` files.

For Figma-first UX design workflows, design systems, design tokens, component
library guidance, Figma annotations, design-to-code handoff, or
`/ux-design-agent`, also read
`docs/agent-framework/skillsets/ux-design-agent/` files.

For Codex skill-library setup, context-budget warnings, plugin-heavy installs,
or skill add/update/remove work, also read
`docs/agent-framework/SKILL_LIBRARY_ROUTER_IMPORT_PROMPT.md` and
`docs/agent-framework/skillsets/skill-library-router/` files.

For optional context acceleration with a chosen graph, generated wiki, symbol
index, code-review graph, or similar accelerator, also read
`docs/agent-framework/CONTEXT_ACCELERATION.md`,
`docs/agent-framework/skillsets/context-acceleration/`, and the repo-local
operator documentation package for the selected tool.

## Repo-Specific Overlay

Replace this section with local rules:

- Source-of-truth order:
  1. Current user request.
  2. Issue or task acceptance criteria.
  3. Approved designs, specs, or architecture docs.
  4. Runtime contracts and existing behavior.
  5. Existing code conventions in the affected area.
- Architecture boundaries: `[fill in]`
- Required validation commands: `[fill in]`
- Harness capabilities: `[sub-agents/cross-agent counterpart/model routing/cache/validation executor availability]`
- MCP and external integration routing: `[repo/folder/workflow allow-list or disabled]`
- Context accelerator: `[none/adopted tool, artifact path, operator docs, freshness, scope, supported modes, artifact policy, verification boundary]`
- Framework path and manifest: `[fill in]`
- Journaling requirement: `[enabled/disabled and path]`
- Release or deployment rules: `[fill in]`

## Required Behavior

- Analyze before acting.
- Plan before editing.
- Map the impacted surface.
- Verify the framework manifest and active harness capabilities.
- Route work through the harness only when useful and supported.
- Challenge directives, journals, memories, cached conclusions, and prior
  project patterns as evidence, not authority. For non-trivial planning or
  architecture, use an independent model/counterpart critique when available;
  include the authorization sentence in advisor briefs and preserve
  source-of-truth precedence.
- If the live user prompt includes the exact phrase `subagents swarm allowed`,
  treat it as explicit authorization and request wording for sub-agents,
  parallel delegation, model routing, and cross-agent counterpart routing when
  useful and supported, without bypassing capability, privacy, safety, budget,
  stop-condition, anti-drift, or validation checks.
- When another AI tool participates, create the communication plan before joint work and keep a single-agent fallback.
- Route bounded and bulk execution to Codex through the live verified route.
  Keep architecture, security, authentication, data-loss, release, and final
  review work on Claude; do not send bulk work to Claude.
- Use an independent counterpart only when it adds evidence. Hermes PR reviews
  run on Codex through `bb fleet validate` with bounded review context.
- Do not use GLM or a GLM-backed Hermes route. OpenCode is legacy and opt-in;
  it is not a default execution path.
- Treat subagent concurrency as finite. In Codex environments that expose a
  thread ceiling, prefer a supported limit of 16 concurrent threads unless local
  policy sets a stricter limit.
- Close completed, idle, stale, or prior-workflow agents after capturing any
  needed result or resume packet, and open fresh agents for new delegated work
  instead of reusing stale context.
- Before using MCPs or external integrations, confirm they are enabled for the
  current repo, folder, or workflow. Ask before using unrecorded connections.
- If the repo adopts a context accelerator, verify freshness, scope, supported
  modes, trust, operator documentation package, privacy boundary, and artifact
  policy before using it. Use it at full useful capability for orientation and
  scoping, but treat generated claims as advisory until primary sources verify
  them.
- Use the skill-library router proactively. Before assuming no specialized skill
  applies, match task language against the refreshed index's names, aliases,
  routing terms, search text, plugin/source, and paths; load the narrowest
  matching skill directly even when the user did not name it.
- For Codex skill or plugin add/update/remove work, refresh the installed
  `skill-library-router` index and run its `--check` mode, or report the
  sandbox or permission blocker.
- Reset active context on workflow, repo, incident, or objective changes.
- When implementation shape is uncertain and repo-local evidence is
  insufficient, scan sibling projects only under configured workspace roots
  metadata-first for candidate patterns and verify fit before adopting. Resolve
  roots from repo adoption settings, harness workspace roots,
  `AGENT_WORKSPACE_ROOTS`, or explicit user input; never hardcode a personal
  `~/projects` path in portable instructions.
- Keep changes scoped.
- Run focused validation first.
- Report failed, blocked, skipped, and not-run checks explicitly.
- Do not add AI attribution, generated-by footers, model signatures, or
  watermarks to code, docs, PR bodies, comments, commits, or review surfaces
  unless the user explicitly asks for that attribution.
- PR bodies must stay minimal: `Summary`, `Changes and value`, and `Ticket`
  only when applicable. The value section must add concrete, non-repetitive app
  value details; do not add approach, validation, deployment, risk, follow-up,
  checklist, rollback, residual-risk, testing, or command-log sections.
