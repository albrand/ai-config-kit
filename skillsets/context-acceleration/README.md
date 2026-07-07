# Context Acceleration Skillset

Use this skillset when a repo or user opts into a context accelerator such as a
Graphify-compatible knowledge graph / context map, an OpenWiki-compatible
generated agent wiki, a symbol index, or a code-review graph.

The workflow is optional and advisory. It helps an agent use the selected tool
at full useful capability for orientation, scope mapping, blast-radius analysis,
business-rule discovery, delegation briefs, and token-economy assessment without
treating generated output as source of truth.

Adoption also requires a repo-local operator documentation package. A generated
graph, wiki, or index is not considered ready if agents and humans cannot tell
how to query it, read its vocabulary, refresh it, verify its claims, and recover
when it is stale or misleading.

## Runtime Model

- Do not require a specific vendor or library.
- Use the selected accelerator only after capability, freshness, scope, and
  trust are checked.
- Require practical documentation for usage examples, graph or wiki vocabulary,
  common workflows, refresh commands, privacy policy, verification boundary,
  troubleshooting, and token-impact measurement.
- Verify load-bearing claims against source files, tickets or board state,
  tests, runtime, config, and accepted task criteria.
- Keep generated artifacts local and ignored by default unless the team reviews
  and opts into committing them.
- Label token impact as measured, vendor-reported, or estimate-only.

## Files

| Path | Purpose |
| --- | --- |
| `codex/context-acceleration/SKILL.md` | Codex skill for the optional context acceleration workflow. |
| `codex/context-acceleration/agents/openai.yaml` | Optional Codex UI metadata. |
| `../../CONTEXT_ACCELERATION.md` | Shared framework doctrine for harnesses and agents. |

## Install

Codex:

1. Copy `codex/context-acceleration/` to `<CODEX_HOME>/skills/context-acceleration/`.
2. Refresh the skill index when `skill-library-router` is installed.
3. Use `$context-acceleration` when a repo adopts or evaluates a graph, wiki,
   symbol index, or code-review graph.

Generic AI:

1. Paste `CONTEXT_ACCELERATION.md` and `codex/context-acceleration/SKILL.md`.
2. Provide the selected tool's graph report, metadata, wiki quickstart, update
   metadata, MCP config, operator documentation package, repo-local skill, or
   equivalent capability evidence.
3. Ask the AI to use the selected accelerator at full useful capability while
   verifying load-bearing claims against primary sources.
