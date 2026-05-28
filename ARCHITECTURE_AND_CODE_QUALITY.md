# Architecture And Code Quality

This document defines generic architecture and code-quality expectations for agent work.

## Architecture Review Requirements

Before implementing non-trivial changes, inspect:

- Entry points.
- Module boundaries.
- Call graph.
- Data flow.
- State ownership.
- External integrations.
- Security boundaries.
- Configuration and environment contracts.
- Tests and validation paths.
- Release and rollback impact.

State:

- What boundary owns the behavior.
- What should stay unchanged.
- What abstraction, if any, is justified.
- What validation proves the change.

## Boundary Principles

Keep responsibilities separate:

- UI or presentation renders prepared data.
- Hooks or controllers orchestrate state and side effects.
- Services own domain rules.
- Repositories or adapters own external data access.
- Schemas own validation shape.
- Utilities stay mechanical and small.
- Config is read through validated helpers.

If a repo uses different names, use the repo's names, but preserve the separation.

## Architecture Deepening Review

Use when assessing or hardening a legacy codebase, preparing a refactor plan, or improving AI navigability.

Look for:

- Shallow modules whose interface is almost as complex as their implementation.
- Concepts that require bouncing across many files to understand one behavior.
- Test seams that exist only on extracted helpers while real bugs hide in orchestration.
- Pass-through abstractions that do not reduce caller knowledge.
- Domain terms that appear under several names across code, docs, and tickets.
- Interfaces with unclear invariants, error modes, ordering, configuration, or ownership.

Prefer hardening candidates that improve:

- Locality: future changes concentrate in fewer places.
- Leverage: callers get more behavior through a smaller, clearer interface.
- Testability: important behavior can be tested through the interface that production uses.
- Domain language: names match the glossary, tickets, docs, and user-visible concepts.

Do not propose new interfaces before confirming the real friction and affected callers. If a proposed hardening direction conflicts with an ADR or current architecture rule, surface the conflict and ask before planning implementation.

## Code Quality Doctrine

Prefer:

- Small files.
- Small functions.
- Single responsibility modules.
- Explicit names.
- Guard clauses.
- Low nesting.
- Narrow interfaces.
- Localized side effects.
- Tests that exercise behavior.

Avoid:

- God files.
- Large render bodies.
- Boolean flag clumps.
- Primitive obsession for meaningful domain values.
- Hidden global state.
- Repeated data shaping in UI.
- Direct external clients in presentation layers.
- Unbounded retries or polling.
- Fire-and-forget async work unless explicitly designed.

## Object-Calisthenics-Inspired Rules

Use these as review criteria:

- One responsibility per module.
- Keep indentation shallow.
- Prefer guard clauses over nested branches.
- Avoid `else` after `return`.
- Avoid nested ternaries.
- Wrap meaningful primitives when it clarifies domain intent.
- Prefer first-class collections over parallel arrays.
- Name values for meaning, not mechanics.
- Keep one clear hop at a time in orchestration code.

These rules are not dogma. Apply them pragmatically, but explain exceptions.

## Complexity Management

When touching complex files:

- Measure or estimate complexity.
- Extract helpers when branches multiply.
- Split orchestration from rendering.
- Split data mapping from side effects.
- Avoid adding new logic to already oversized files when extraction is practical.
- Do not expand allowlists or exceptions without explicit approval.

Suggested default thresholds, adjustable per repo:

- Function complexity: warn above 12, review carefully above 16.
- File size: split when a file mixes responsibilities or becomes hard to review.
- Component size: split stateful shell from stateless leaves when rendering and orchestration mix.

## State Flow Review

For state changes, inspect:

- Source of truth.
- Derived versus stored state.
- Cache keys.
- Invalidation paths.
- Optimistic update and rollback paths.
- Duplicate refetches.
- Loading and error states.
- Stale local copies.
- Client/server or process boundary leaks.

Prefer:

- Derived state over mirrored state.
- Stable inputs.
- Explicit invalidation.
- Narrow updates.
- Rollback on failure.

## Data Flow Review

For data changes, inspect:

- Query filters.
- Account or workspace isolation.
- Pagination.
- Sorting.
- N+1 risk.
- Overfetching.
- DTO shape.
- Input validation.
- Error translation.

Prefer:

- Narrow selects.
- Explicit filters.
- Stable response contracts.
- Clear error shapes.
- Tests around important filters and edge cases.

## Security Review

For security-sensitive changes, inspect:

- Authentication boundary.
- Authorization boundary.
- Account or workspace isolation.
- Input validation.
- Output redaction.
- Secret handling.
- Logging.
- Webhook or callback verification.
- Public error responses.

Never rely on UI gating alone for protected behavior.

## Performance Review

Look for:

- Serial requests that can run in parallel.
- Repeated scans over the same array or collection.
- Overfetching large payloads.
- Unnecessary re-renders.
- Recomputed expensive transforms.
- Unbounded polling or retries.
- Cache invalidation that reloads unrelated data.

Prefer:

- Parallel independent requests.
- Single-pass grouping.
- Indexed lookups.
- Memoized derived data where appropriate.
- Narrow invalidation.

## Code Quality Self-Review Checklist

Before completion:

- [ ] Changed files have a clear owner and responsibility.
- [ ] New logic is not hidden in presentation code.
- [ ] Names are explicit.
- [ ] Control flow is readable.
- [ ] No obvious duplication was introduced.
- [ ] Data and security boundaries are preserved.
- [ ] Tests cover the behavior at the right layer.
- [ ] Validation results are reported truthfully.
