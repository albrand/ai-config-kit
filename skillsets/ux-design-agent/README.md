# UX Design Agent Skillset

Use this skillset in either of two modes:

- **Design-maker mode** — a design-maker (UX designer, product designer, founder, product owner, or product team) wants an AI to act as a personal design partner for live-mockup design, design-system setup, design-token implementation, personal designer-agent shaping, and code-aware design handoff.
- **Prototype-consumption / backlog-shaping mode (PO mode)** — a product owner, stakeholder, implementation lead, or designer brings an existing prototype, Figma file, screenshots, or repo to UNDERSTAND, then shape or create/update backlog tickets.

The agent detects the active mode and says so. In design-maker mode it treats the live mockup (often a Next.js app deployed to Vercel) as the active design surface, enforces one durable design source of truth, runs a design signoff when a mockup is finished, and propagates the signed-off UI to both the source of truth (Figma by default) and the ticket board — creating or updating tickets and recording that the revision was posted. In PO mode it inventories the design source (screens, flows, components, tokens, typography, states, responsive and accessibility behavior, design-system conventions), surfaces open questions and implementation dependencies, and produces a board-ready, board-agnostic backlog of PR-sized vertical-slice tickets.

The workflow is inquisitive by default: the agent should help the user make good product and interface decisions without requiring them to speak like an engineer. It should explain tradeoffs plainly, ask targeted questions, drive opinionated defaults, and keep the work grounded in modern UX practice, accessible UI patterns, and the actual project or design system.

## Runtime Model

This is an AI-runbook skillset.

- Use normal AI capabilities: inspect repos, read design-system docs, inspect Figma files through MCP when available, use connected design tools, reason over product goals, ask questions, create/update artifacts when approved, and validate design/code alignment.
- Do not depend on custom scripts, generated parsers, or one-off automation.
- Prefer component libraries such as shadcn/ui when the project stack fits, but inspect the existing stack before recommending or installing anything.
- Treat the live mockup as the active design surface; Figma is the durable design source of truth and a propagation target. If the user names another source of truth, honor it.
- Enforce one durable design source of truth before signoff and board propagation. Default to Figma; if none, introduce the concept and require a choice (Figma, Confluence/Notion, Google Doc, or repo docs).
- Ask for Figma MCP, board MCP (Linear, Jira, or the user-selected board/tracker), Vercel/preview tooling, file access, and relevant design-tool access before promising live edits or writes.
- If Claude is the active tool, Claude Code orchestrates the workflow and Claude Design (the AI design-execution capability, in practice a connected Figma MCP server and its companion design skills) must be used for design creation or visual design execution when available. When those skills are present, load the matching prerequisite skill before each design tool call (e.g. `figma-use` before `use_figma`).
- When creating a personal designer agent, capture the designer's question style, Figma workspace conventions, visual taste boundaries, product defaults, tooling defaults, and output preferences before production work.

## Files

| Path | Purpose |
| --- | --- |
| `codex/ux-design-agent/SKILL.md` | Codex skill for both UX workflows: design-maker (live mockup, source of truth, signoff, Figma + board handoff) and prototype-consumption/backlog-shaping (PO). |
| `codex/ux-design-agent/references/output-contract.md` | Installed Codex reference checklist. |
| `codex/ux-design-agent/agents/openai.yaml` | Codex UI metadata. |
| `claude/commands/ux-design-agent.md` | Claude Code slash command mirror for `/ux-design-agent`. |
| `references/output-contract.md` | Shared output and validation contract. |

## Install

Codex:

1. Copy `codex/ux-design-agent/SKILL.md` to `<CODEX_HOME>/skills/ux-design-agent/SKILL.md`.
2. Copy `codex/ux-design-agent/references/output-contract.md` to `<CODEX_HOME>/skills/ux-design-agent/references/output-contract.md`.
3. Copy `codex/ux-design-agent/agents/openai.yaml` to `<CODEX_HOME>/skills/ux-design-agent/agents/openai.yaml` when the Codex UI metadata format is used.

Claude Code:

1. Copy `claude/commands/ux-design-agent.md` to `~/.claude/commands/ux-design-agent.md` or a project `.claude/commands/` folder.
2. Run `/ux-design-agent <product, Figma, repo, or design-system prompt>`.
3. Ensure design-execution tooling (Claude Design — in practice a connected Figma MCP server and its companion skills) is available for actual visual design generation or design-file work. If it is unavailable, produce a paste-ready design brief and Figma execution plan instead of pretending the design was created.

Generic AI:

1. Paste this README plus `references/output-contract.md`.
2. Provide the product prompt, Figma links or exports, repo path if relevant, brand inputs, and target audience.
3. Ask the AI to follow the workflow and report capability gaps before design or repo writes.

## Completion Bar

The workflow is complete only when it reports:

- The skill mode detected and announced (design-maker or prototype-consumption/backlog-shaping).
- Whether the prompt was detected and announced as design-making, or deferred.
- Sources inspected and unavailable.
- Figma, board (Linear, Jira, or the chosen board/tracker), Vercel/preview, repo, component-library, and design-token capabilities verified or blocked.
- The chosen design source of truth, whether it was enforced, and whether it was kept current.
- Questions asked, answered, defaulted, or deferred.
- Whether the project is new or existing.
- Whether tokens and system design conventions were found, created, imported, or only proposed.
- Live mockup status and shareable preview URL (design-maker mode).
- Design signoff status (approved or pending) and what it covers (design-maker mode).
- Design inventory with evidence and gaps: screens/flows, components, tokens, typography, states, responsive, accessibility (PO mode).
- Open questions and implementation dependencies, ranked (PO mode).
- Ticket set: hierarchy, PR-sized vertical slices with acceptance criteria and design-evidence links; status PROPOSED vs. CREATED (PO mode).
- Figma annotations or proposed annotation map, and propagation to the source of truth.
- Board propagation: ticket format proposed or tickets created/updated, and the revision comment posted.
- Design-system and component decisions, including shadcn/ui or another library when appropriate.
- Accessibility, responsive behavior, states, and handoff validation.
- Repo/design artifacts changed, proposed, blocked, or left unchanged.
