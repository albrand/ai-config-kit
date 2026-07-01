# UX Design Agent Output Contract

Use this checklist for substantial UX design-agent work in either mode: design-maker (live mockup, design signoff, Figma propagation) or prototype-consumption/backlog-shaping (PO) mode (inventory an existing design and shape a board-ready backlog). Also use it for board/ticket handoff, design tokens, system conventions, or repo implementation.

## Skill Mode

- Which mode was detected and announced: design-maker or prototype-consumption/backlog-shaping (PO).
- If ambiguous, which clarifying question was asked and which mode leads.

## Design-Maker Detection

- Whether the prompt was read as design-making and announced as such, or deferred (with reason).

## Capability Report

- Figma MCP/tool access: available, blocked, unavailable, or not needed.
- Figma edit access and target file/library.
- Board MCP access: Linear, Jira, another connected board/tracker, or none.
- Vercel/preview-deploy tooling access.
- Repo read/write access.
- Component-library status.
- Token and design-system evidence inspected.
- Claude Design status when running through Claude.
- Browser, screenshot, or visual validation status.

## Source Of Truth

- Chosen SoT location: Figma, Confluence/Notion, Google Doc, repo docs, or none yet.
- Whether a SoT was enforced before signoff/propagation.
- Whether the SoT was kept current with the mockup changes.

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

## Live Mockup And Preview

- Mockup framework and project (e.g. Next.js).
- Preview deploy status and shareable preview URL (and the deploy/commit it reflects).
- Whether the mockup was built from tokens/components and kept in step with the SoT.

## Design Signoff

State one: approved, pending approval, or not reached.

Per signed-off surface, confirm coverage of:

- How it looks: layout, hierarchy, tokens, typography.
- How it behaves: actions, navigation, interactions, transitions, and states.
- Responsive behavior and accessibility.
- Components used and their granularity.
- Open questions and non-goals.

## Prototype Consumption And Backlog Shaping (PO Mode)

Report when PO mode is active:

- Design source inspected: prototype URL, Figma file/link, screenshots, repo, docs — and what was readable vs. blocked.
- Design inventory: screens/flows, components, tokens, typography, states, responsive behavior, accessibility signals, design-system conventions — each tied to evidence, with gaps marked unknown.
- Open questions and implementation dependencies, ranked by scope/sequencing impact.
- Ticket set: hierarchy (initiative/epic → feature → PR-sized vertical slice), each with type, user job, acceptance criteria, validation, design-evidence links, and dependencies (tokens, components, states, APIs, permissions).
- Ticket status: PROPOSED vs. CREATED for each. Never blur the two.
- Whether the user selected a board/tracker other than Jira or Linear, and whether it was honored.

## Board Propagation

- Board tool: Linear, Jira, the user-selected board/tracker, or none.
- New project/tickets: structure and ticket format proposed; classification (Feature, Bug Fix, Chore, Spike); created or proposed only.
- Existing tickets: which ticket owns the UI piece (or which inventory item maps to it in PO mode), updated with the new UI version (Figma + preview links refreshed) or the proposed link/AC/dependency updates.
- Revision comment posted recording that the change was made (`save_comment` for Linear, `addCommentToJiraIssue` for Jira, or the chosen board's equivalent).
- Approval status for every board write.

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

Skill mode: design-maker / prototype-consumption+backlog-shaping
Detection: design-making (announced) / deferred
Personal profile: ...
Project mode: ...
Capabilities: ...
Source of truth: ...
Decisions: ...
Live mockup + preview: ...
Signoff: approved / pending — coverage ...
Design inventory (PO): screens/flows, components, tokens, typography, states, responsive, accessibility — evidence + gaps
Open questions + dependencies (PO): ...
Ticket set (PO): hierarchy, PR-sized slices with AC + design evidence; status PROPOSED vs. CREATED
Figma (or SoT) propagation: ...
Board propagation: tool, tickets created/updated, comments posted ...
Artifacts: ...
Validation: ...
Blocked or unverified: ...
Next step: ...
```
