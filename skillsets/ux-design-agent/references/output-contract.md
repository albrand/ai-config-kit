# UX Design Agent Output Contract

Use this checklist for substantial UX design-agent work, especially when Figma, design tokens, system conventions, or repo implementation are in scope.

## Capability Report

- Figma MCP/tool access: available, blocked, unavailable, or not needed.
- Figma edit access and target file/library.
- Repo read/write access.
- Component-library status.
- Token and design-system evidence inspected.
- Claude Design status when running through Claude.
- Browser, screenshot, or visual validation status.

## Intake Summary

- Product and audience.
- Primary user job.
- Target surfaces and workflows.
- Brand and tone inputs.
- Source-of-truth order.
- Constraints and non-goals.
- Questions asked, user answers, recommended defaults, and deferred decisions.

## Personal Agent Profile

Include when the request is to create or shape a UX designer's personal agent:

- Preferred question style.
- Figma workspace and annotation conventions.
- Visual taste boundaries.
- Product decision defaults.
- Tooling defaults.
- Output defaults.
- Reusable instructions or profile location, if written.

## Mode Detection

State one:

- `New project`.
- `Existing project without system`.
- `Existing project with system`.
- `External design system`.

Include evidence for the mode. Do not rely only on the user's wording when repo or Figma evidence is available.

## Design Tokens

Report whether tokens were:

- Created from scratch.
- Imported from an existing source.
- Mapped from Figma or repo evidence.
- Proposed only.
- Blocked.

Cover relevant token categories: color, typography, spacing, layout, radius, depth, motion, state, component, accessibility, and theme tokens.

## System Design Convention

Report whether conventions were:

- Created.
- Updated.
- Reused.
- Proposed only.
- Blocked.

Include source-of-truth order, component naming, variants, responsive rules, accessibility rules, annotation standards, and handoff rules.

## Component Library Decision

Include:

- Recommended library or existing system.
- Why it fits the stack and design goals.
- Whether shadcn/ui is recommended, already present, not applicable, or deferred.
- Approval needed before installation or migration.

## Figma Work Or Plan

Include:

- Files/pages/frames/components touched or proposed.
- Variables, styles, components, and variants created or mapped.
- Annotation coverage: decisions, tokens, states, responsive behavior, accessibility, open questions, and implementation notes.
- Navigation aids for the UX designer: page/frame names, section labels, links, or ordered review path.

## UX Validation

Check:

- Information hierarchy.
- Mobile-first responsiveness.
- Accessibility and contrast.
- Focus, keyboard, and touch targets.
- Loading, empty, error, permission, disabled, hover, focus, selected, and success states.
- Text fit and localization length.
- Product-domain fit.
- Implementation feasibility.

## Final Report

Use this shape:

```md
**UX Design Agent Result**

Personal profile: ...
Mode: ...
Capabilities: ...
Decisions: ...
Artifacts: ...
Figma annotations: ...
Validation: ...
Blocked or unverified: ...
Next step: ...
```
