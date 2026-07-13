# Plan Module Delivery Output Contract

Load this reference when preparing or reviewing final module-planning artifacts.

## Minimum Project Description Sections

- `Overview`: module purpose and outcome in plain language.
- `Module Boundary`: what belongs to this module and what does not.
- `Current Experience Baseline`: source-backed behavior that must be migrated or preserved.
- `Target Experience`: expected future-state behavior.
- `Planning Estimate`: explicitly state that dates are estimates, not commitments.
- `Phases`: simple phase names with goals, entry criteria, exit evidence, and dependencies.
- `Resolved Decisions`: decisions already answered by evidence or requester input.
- `Open Questions`: unanswered items with owner, impact, and suggested default where possible.
- `Resources`: links to docs, repos, source files, designs, PRs, APIs, and board artifacts.
- `Risks`: impact, mitigation, owner, and whether the risk blocks planning or execution.
- `Ticket Sizing Policy`: one issue should map to one PR.

## Minimum Ticket Sections

- `Objective`
- `Scope`
- `Acceptance Criteria`
- `Validation`
- `Dependencies`
- `Resources`
- `Owner/Estimate` when available
- `Open Questions` when relevant

## Ticket Quality Checklist

- The title is phase-scoped and easy to scan.
- The work can reasonably fit in one PR.
- The issue implements or validates module functionality.
- The issue is not broad process work, unrelated scaffold work, or another module's responsibility.
- Acceptance criteria are observable by product and engineering.
- Validation is concrete enough to run or inspect.
- Resources are directly useful, not decorative links.
- Open questions are not already answered in source evidence.

## Final Review Checklist

- Active issues are grouped into simple phases.
- Phase order follows real dependencies.
- Priorities reflect critical path and user instruction.
- Dates, if present, are estimation markers only.
- Leadership can understand why the module matters.
- Product can understand what user outcomes are being delivered.
- Engineering can start implementation without redoing discovery.
- Remaining risks and blockers are visible.
