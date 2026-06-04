# Repo Adoption Playbook

Use this guide to adopt the framework in a repository.

## Phase 1: Inventory

Collect:

- Existing agent instruction files.
- Existing framework files, if any.
- Contributor docs.
- Architecture docs.
- Testing docs.
- Release docs.
- Issue or delivery workflow docs.
- CI configuration.
- Lint, typecheck, test, and build commands.
- Known fragile areas.

Do not copy closed-scope details into the shared framework. Keep local details in the repo.
Use `FRAMEWORK_MANIFEST.md` to compare the existing setup against the canonical file set.

## Phase 2: Choose Local Layers

Decide which layers the repo will use:

- Universal bootstrap file.
- Config-kit ingestion prompt.
- Framework manifest.
- Tool-specific adapter file.
- Repo-root instruction file.
- Parent directory instruction file.
- Repo-local skills.
- Local process docs.
- Local session journals.
- Automated gates.

Record the chosen framework path, for example `docs/agent-framework/`, and keep adapter imports aligned with that path.

## Phase 3: Create Repo Instructions

Copy `REPO_AGENTS_TEMPLATE.md` into the repo as the appropriate instruction file for the agent tool.

Fill in:

- Source-of-truth order.
- Required first steps.
- Architecture boundaries.
- Data and security rules.
- State and performance rules.
- Testing rules.
- Validation commands.
- Optional invokable processes.
- Completion report requirements.

Also choose one adapter path:

- Generic: copy `adapters/AGENTS.md` to the repo root.
- Claude Code: copy `adapters/CLAUDE.md` to the repo root and keep the imports current.
- Gemini CLI: copy `adapters/GEMINI.md` to the repo root and keep the imports current.
- Cursor: copy `adapters/cursor-agent-framework.mdc` to `.cursor/rules/agent-framework.mdc`.
- Chat-only tools: paste `adapters/GENERIC_AI_PROMPT.md`.
- Chat tools with enough context: paste `CONFIG_KIT_AI_PROMPT.md`, then attach or paste the task-relevant framework files.

Then fill the local harness capability record:

- File read and edit access.
- Shell and validation execution.
- Sub-agents or delegation.
- Cross-agent counterpart access.
- Model routing.
- Cache or memory.
- Network or external tools.
- Browser or UI verification.
- Journal persistence.

## Phase 4: Add Journaling If Needed

If the repo adopts journals:

- Create a journal location.
- Decide local-only or versioned.
- Add ignore rules if local-only.
- Add commands or a manual format.
- Add journal start/resume/close requirements to repo instructions.

## Phase 5: Define Quality Gates

Define:

- Focused validation command.
- Lint command.
- Typecheck command.
- Test command.
- Build command.
- Security or policy checks.
- Generated artifact checks.
- Release readiness checks.
- Quality convergence targets and iteration limits for high-risk work.

Classify each as:

- Always required.
- Required for code changes.
- Required for cross-cutting changes.
- Required for release changes.
- Optional or best effort.

## Phase 6: Add Repo-Local Skills

Add repo-local skills only when needed.

Good candidates:

- Architecture review for the repo's stack.
- Design-contract review.
- Release readiness.
- Data migration review.
- Security-sensitive debugging.
- Ticket-first delivery workflow.

Executable shared skillsets should be installed deliberately:

- Share `SKILL_LIBRARY_ROUTER_IMPORT_PROMPT.md` with operators who want an assistant to import the Codex Skill Library Router, keep large skill libraries indexed, and verify smart access after skill or plugin changes.
- Share `ECOSYSTEM_TERRAFORM_GUIDE.md` with operators so they understand which command to use and can start from tested prompt samples.
- Share `UX_DESIGN_AGENT_IMPORT_PROMPT.md` with operators who want an assistant to import the UX Design Agent into Codex or Claude Code with overwrite checks and verification.
- Claude Code: copy `skillsets/*/claude/commands/*.md` to the project `.claude/commands/` folder or user `~/.claude/commands/`.
- Codex: copy the relevant `skillsets/*/codex/*/SKILL.md` into `<CODEX_HOME>/skills/<skill-name>/SKILL.md`.
- Codex with large skill libraries: install `skillsets/skill-library-router/codex/skill-library-router/`, run its `refresh-skill-index.cjs` script, then run the same script with `--check`.
- Keep shared references such as `ecosystem-output-contract.md` near the installed framework path so commands can load them.
- Ask before enabling or running commands that can mutate trackers, cloud resources, repositories, CI settings, or secrets.

## Phase 7: First Session Verification

Start a fresh agent session and ask:

```text
List the instruction layers you can see for this repository.
For each layer, summarize what rules you will apply.
State which bootstrap or adapter file you loaded.
State whether `CONFIG_KIT_AI_PROMPT.md` was loaded.
State which manifest file you loaded.
State the active harness capability record.
State whether cross-agent counterpart access is available, blocked, unavailable, or not useful.
Also state which validation commands are required for code changes.
Do not edit files.
```

Confirm:

- The agent finds the correct instruction files.
- The agent distinguishes global and repo-local rules.
- The agent loaded the intended bootstrap or adapter.
- The agent loaded the config-kit ingestion prompt when available.
- The agent loaded the framework manifest.
- The agent reports unavailable or limited harness capabilities.
- The agent reports cross-agent counterpart availability and fallback.
- The agent identifies validation commands.
- The agent knows when to ask about conflicts.
- The agent knows whether journals are required.

## Phase 8: Trial Task

Run a small, low-risk task.

Evaluate:

- Did the agent plan before editing?
- Did it inspect enough context?
- Did it avoid unrelated changes?
- Did it use the correct validation?
- Did it report skipped or blocked checks truthfully?
- Did it report harness capability gaps truthfully?
- Did it create a communication plan before using another AI tool, or state why paired work was unavailable or not useful?
- Did it use a convergence loop when first-pass validation was insufficient?
- Did it update the journal if required?

## Phase 9: Maintain

Review the repo setup periodically:

- Remove stale rules.
- Promote repeated lessons to skills.
- Move enforceable rules into lint, tests, CI, or scripts.
- Keep validation commands current.
- Keep closed-scope details local.

## Adoption Definition Of Done

A repo has adopted the framework when:

- It has a repo instruction file.
- It has a bootstrap or adapter path for the AI tools the team uses.
- It has a framework manifest path and the canonical required files.
- It defines source-of-truth order.
- It defines architecture boundaries.
- It defines required validation.
- It records harness capabilities.
- It states whether journaling is required.
- It defines review and PR expectations.
- If Codex skills or plugins are installed, it has either a fresh Skill Library Router index or an explicit note that indexing is not applicable or blocked.
- A fresh agent session can correctly summarize the local rules.
