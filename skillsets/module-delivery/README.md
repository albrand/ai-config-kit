# Module Delivery Skillset

Use this skillset when a user gives an AI a module name, capability area, roadmap item, migration target, or board-planning request and expects the AI to turn it into an evidence-backed delivery plan.

This is separate from the developer runbook. It is not a code implementation workflow. It is a product-and-engineering planning workflow for creating or updating project descriptions, phases, milestones, PR-sized tickets, resource links, risks, owners, and validation gates.

## Runtime Model

This skillset is intentionally AI-runbook based.

- Do not depend on Python, Node, shell validators, generated scripts, custom parsers, or helper automation.
- Use normal AI capabilities: read files, search docs, inspect available repositories, inspect connected boards through MCP when available, reason over evidence, ask targeted questions, and write or update artifacts only when the user asked for that.
- Read-only discovery commands such as `rg`, `find`, `git status`, and `git diff` may help inspect source evidence, but they are not required and must not become a workflow dependency.
- Before board updates, PR creation, issue linking, deployment checks, or design-resource inspection, verify required channels such as GitHub CLI or MCP, Linear MCP, Vercel MCP/CLI, Figma MCP, repo checkout access, and network/browser access.
- Ask the user to install, connect, or authorize missing capabilities when they are required. Do not silently downgrade to paste-only output unless the user accepts that fallback.

## Files

| Path | Purpose |
| --- | --- |
| `codex/SKILL.md` | Codex skill for `plan-module-delivery`. |
| `claude/commands/plan-module-delivery.md` | Claude Code slash command mirror for `/plan-module-delivery`. |
| `references/output-contract.md` | Shared checklist for project descriptions, tickets, and final review. |

## Install

Codex:

1. Copy `codex/SKILL.md` to `<CODEX_HOME>/skills/plan-module-delivery/SKILL.md`.
2. Copy `references/output-contract.md` to `<CODEX_HOME>/skills/plan-module-delivery/references/output-contract.md`.
3. If the Codex UI metadata format is used, create the matching `agents/openai.yaml` in that skill folder.

Claude Code:

1. Copy `claude/commands/plan-module-delivery.md` to `~/.claude/commands/plan-module-delivery.md` or a project `.claude/commands/` folder.
2. Run `/plan-module-delivery <module description>` from Claude Code.

Generic AI:

1. Paste this README plus `references/output-contract.md`.
2. Provide the module description and relevant docs/repos/board access.
3. Ask the AI to follow the workflow without relying on scripts or custom automation.
