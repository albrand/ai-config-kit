# Shared feature granularity rules

Paths written as `references/...` below are relative to this skill folder.

## Feature Granularity

Decide the right altitude before creating tickets or Figma frames. This applies in both modes: design-maker mode splits a finished mockup for handoff; PO mode splits the consumed inventory directly into the backlog.

- Read the surface and split it into shippable units: initiative or epic, feature, vertical slice, then PR-sized change.
- A "feature" is a coherent user-facing capability (for example, "Loan application review screen"), not a whole product and not a single button.
- Each feature must have a Figma home containing the components it uses, the design tokens it relies on, and its typography when type decisions apply. If a feature reuses an existing component or token, reference it instead of duplicating.
- Match ticket granularity to the feature: one feature ticket per coherent capability, with sub-tickets or checklist items for slices when the feature is large.

