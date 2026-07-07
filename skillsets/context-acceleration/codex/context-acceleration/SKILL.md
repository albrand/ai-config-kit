---
name: context-acceleration
description: Gate and use optional repository context accelerators such as Graphify-compatible graphs/context maps, OpenWiki-compatible generated agent wikis, symbol indexes, or code-review graphs. Use when the user or repo opts into one of these tools, asks for token-saving context strategy, scope mapping, blast-radius analysis, business-rule discovery, accelerator adoption guidance, or repo-local accelerator skill and instruction updates.
---

# Context Acceleration

Use this skill only when a context accelerator is chosen or being evaluated.
The accelerator is optional and advisory; if none is adopted, use normal
progressive disclosure.

## Source Doctrine

1. Load `CONTEXT_ACCELERATION.md` when it exists in the framework or repo.
2. Load the active workflow doctrine needed by the task, usually
   `HARNESS_STRATEGY.md`, `TOKEN_ECONOMY.md`, `SKILLS_CATALOG.md`, and repo
   instructions.
3. Treat graph, wiki, index, and semantic output as routing evidence, not
   source of truth. Source files, tickets or board state, tests, runtime,
   config, accepted criteria, and higher-priority instructions decide.

## Capability Gate

Before using an accelerator, record:

- Adopted tool class: graph, wiki, graph+wiki, symbol index, code-review graph,
  or none.
- Artifact or access path: local files, MCP, report, metadata, wiki root, or
  generated quickstart.
- Operator documentation path: repo-local docs that explain usage, vocabulary,
  workflows, refresh, privacy, verification, troubleshooting, and token impact.
- Freshness: generated time, source revision, update metadata, stale or
  unknown status.
- Scope: covered paths, languages, modules, docs, schemas, tickets, and known
  exclusions.
- Supported modes: graph query/path/explain/summary/report/MCP, wiki
  quickstart/source-map/update metadata, symbol lookup, or review graph.
- Trust boundary: authorized generation, secret exclusion, ignore policy,
  privacy boundary, and artifact policy.

If the artifact is missing, stale, partial, or untrusted, rebuild or update it
only when the team permits. Otherwise state the gap and fall back to file
indexes, metadata, focused `rg`, source reading, tests, and runtime evidence.
If the raw artifact exists but the documentation package is missing or too thin
to operate the tool confidently, record the accelerator as `limited` or
`blocked` and offer to scaffold the missing documentation before relying on it.

## Documentation Package

When adopting or evaluating an accelerator, require a repo-local documentation
package. It should explain:

- Purpose, covered surfaces, excluded paths, and non-goals.
- Artifact paths, graph metadata, wiki roots, MCP endpoints, and update
  metadata.
- Graph node and edge vocabulary, wiki taxonomy, confidence markers, and
  inferred or semantic claim labels.
- Concrete usage examples: graph queries, path/explain/report calls, wiki
  source-map navigation, symbol lookups, and good prompts.
- Common workflows: orientation, scope mapping, blast radius, business-rule
  discovery, dependency tracing, review focus, and delegation briefs.
- Refresh commands, update cadence, freshness checks, stale symptoms, and
  rebuild failure handling.
- Secret exclusion, ignore policy, artifact commit policy, CI opt-in, and
  private endpoint handling.
- Verification boundary and primary-source checks for load-bearing claims.
- Troubleshooting and fallbacks when outputs are empty, stale, noisy, or
  misleading.
- Token impact ledger: measured local savings, vendor-reported claims, and
  maintenance cost.

Do not treat a barely understandable graph or generated wiki as a mature
capability. The documentation must let a new agent use the accelerator without
reverse-engineering its format from scratch.

## Full-Power Use

When the accelerator is available and trusted, use the strongest useful mode
the selected tool exposes. Do not merely skim a generated page and then perform
a broad raw source sweep.

- Use graph query, path, explain, summary, report, or MCP calls for repo
  orientation, dependency paths, callers, reverse dependencies, ownership,
  business-rule locations, and blast radius.
- Use generated wiki quickstarts, source maps, update metadata, and linked page
  navigation for first-pass orientation and targeted reads.
- Use symbol or code-review graphs to locate definitions, call sites, changed
  contracts, and review hotspots before opening full files.
- Use compact accelerator results in delegation briefs so sidecars do not
  rediscover the same scope.

## Verification

- Verify every load-bearing claim against primary sources before editing,
  reviewing, approving, or making readiness claims.
- Label inferred, semantic, generated, stale, partial, or unverified claims in
  the plan and close-out.
- When accelerator output conflicts with current source files or accepted
  task criteria, prefer current source evidence unless a higher-authority
  artifact supersedes it.
- For security, auth, data, release, or business-critical decisions, treat the
  accelerator as an orientation layer only.

## Token And Capability Assessment

When asked whether the accelerator adds value:

- Estimate savings from avoided broad discovery, repeated agent orientation,
  tighter delegation briefs, and fewer duplicated file reads.
- Separate local measured results from vendor-reported or estimate-only claims.
- Count maintenance cost: generation time, stale-artifact risk, privacy review,
  ignored paths, artifact storage, and CI or indexing overhead.
- Recommend adoption when repeated scope, architecture, business-rule, or
  multi-agent questions are common enough to outweigh maintenance cost.

## Output

Return:

- Capability gate result: adopted tool, status, freshness, scope, modes, trust,
  and fallback.
- Documentation package status: present, missing, stale, too thin, or
  sufficient; include the path and any proposed scaffold.
- Full-power usage plan or usage performed.
- Targeted source verification plan and any verified claims.
- Token or developer-experience impact, labeled as measured,
  vendor-reported, or estimate-only.
- Artifact policy: local, ignored, committed after review, blocked, or not
  applicable.

## Guardrails

- Do not make a graph or wiki accelerator a default dependency.
- Do not commit generated artifacts unless the team opted in and privacy checks
  passed.
- Do not run semantic, media, model-backed, or CI indexing without explicit
  opt-in.
- Do not allow generated wiki tools to mutate instruction files without
  explicit team opt-in and instruction-precedence review.
- Do not paste whole graph dumps or wiki trees into prompts when scoped queries
  or summaries answer the routing question.
