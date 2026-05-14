# Shareable AI Agent Configuration Framework

## Purpose

This framework defines a reusable way to configure AI coding agents across teams.

It standardizes how agents analyze, plan, inspect context, route work through a harness, coordinate with other AI tools when available, delegate, journal, learn durable skills, apply architecture standards, run quality gates, and report validation truth.

It must not include sensitive details, non-public repository names, internal roadmap facts, private URLs, credentials, or closed-scope domain specifics.

## Install These Layers

1. Universal bootstrap
   - Give every AI tool `AI_BOOTSTRAP.md` as the first file or pasted instruction.
   - For generic chat tools, paste `CONFIG_KIT_AI_PROMPT.md` first so the AI knows how to absorb the kit.
   - Give every AI tool `FRAMEWORK_MANIFEST.md` so it can verify required files, load profiles, harness capabilities, and readiness.

2. Tool adapter
   - Use `AI_TOOL_ADAPTERS.md` to choose the right adapter for the AI tool.
   - Copy the matching file from `adapters/` into the repository or tool settings.

3. Global instruction file
   - Use `GLOBAL_AGENTS.md` as the user-level baseline.

4. Global skills
   - Use `SKILLS_CATALOG.md` to define reusable workflows.

5. Harness strategy
   - Use `HARNESS_STRATEGY.md` to define master/sub-agent routing, model tiers, cache rules, anti-drift, escalation, and validation ownership.

6. Cross-agent coordination
   - Use `CROSS_AGENT_COORDINATION.md` when one AI tool coordinates another AI tool as peer critic, explorer, bounded executor, verifier, or summarizer.

7. Quality convergence
   - Use `QUALITY_CONVERGENCE.md` when work needs measured iterations, breakpoints, and explicit stop conditions.

8. Repo instruction file
   - Use `REPO_AGENTS_TEMPLATE.md` in each repository.

9. Repo-local process docs
   - Add only when the workflow is local to that repository.

10. Optional local journals
   - Use `SESSION_JOURNALING.md` if the repo needs resumable execution notes.

## What Belongs Globally

- Collaboration style.
- Analysis and planning.
- Delegation doctrine.
- Harness routing and cache discipline.
- Cross-agent communication plans and single-agent fallback.
- Framework manifest and readiness standards.
- Quality convergence standards.
- Debugging workflow.
- Verification discipline.
- Review posture.
- Skill promotion rules.
- Truthful reporting standards.

## What Belongs In Each Repo

- Architecture boundaries.
- Data ownership and schema rules.
- Auth and permission model.
- Account or workspace isolation.
- Source-of-truth order.
- Delivery workflow.
- Design or UI standards.
- Validation commands.
- Release and deployment workflow.
- Known fragile areas.

## Adoption Checklist

- [ ] Add global baseline instructions.
- [ ] Add the config-kit ingestion prompt for chat-only tools.
- [ ] Add universal bootstrap instructions.
- [ ] Add the framework manifest and required file inventory.
- [ ] Add the adapter for each AI tool the team uses.
- [ ] Add global skills.
- [ ] Define harness support for sub-agents, cross-agent counterpart access, model routing, cache, and validation execution.
- [ ] Add repo instruction file.
- [ ] Define repo source-of-truth order.
- [ ] Define architecture boundaries.
- [ ] Define quality gates.
- [ ] Define quality convergence triggers and stop conditions.
- [ ] Decide whether session journals are required.
- [ ] Add repo-local skills only where needed.
- [ ] Run the adoption verification prompt.

## Maintenance

- Promote repeated behavior into skills.
- Move enforceable rules into lint, tests, CI, or scripts.
- Keep closed-scope details local.
- Remove stale rules.
- Keep validation commands current.

## First Verification Prompt

```text
List the instruction layers you can see for this repository.
For each layer, summarize the rules you will apply.
State which bootstrap or adapter file you loaded.
State whether CONFIG_KIT_AI_PROMPT.md was loaded.
State which framework manifest you loaded.
State which harness capabilities are available.
State whether cross-agent counterpart access is available, blocked, unavailable, or not useful.
State whether session journaling is required.
State which validation commands are required for code changes.
Do not edit files.
```
