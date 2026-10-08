# Prototype consumption and backlog shaping

## Prototype Consumption And Backlog Shaping (PO Mode)

Use this mode when the user brings an existing design to consume rather than redraw. The deliverable is a structured understanding of the design plus a board-ready, board-agnostic backlog. It serves product owners, stakeholders, implementation leads, and designers doing handoff — not only UX designers.

### Intake From The Design Source

Collect and, where access allows, inspect the source directly instead of asking the user to transcribe:

- The design source: prototype URL, Figma file/link, screenshots, exported frames, a repo with UI, product docs, or a combination. Use Figma MCP, screenshot, browser, and repo reads when available.
- Product, audience, user jobs, and the workflow the design supports.
- Scope of the ask: whole prototype, a flow, selected screens, or a component set.
- The target board/tracker and project (Jira, Linear, or another connected board) and whether tickets already exist.
- Constraints: timeline, device focus, accessibility target, localization, release scope.

Do not invent screens or behavior the source does not show. If the source is incomplete, list the gaps as open questions.

### Design Inventory

Produce an evidence-backed inventory of what the source actually contains. Cover what is visible; mark the rest unknown. Tie every item to its evidence (frame name, screen label, screenshot, repo file, token file) — prefer a scannable table.

- Screens and flows: every distinct screen/view, the flow between them, entry/exit points, and the user job each serves.
- Components: reusable components, variants, anatomy, naming, granularity; note one-off vs. system components.
- Design tokens: color, typography, spacing, layout, radius, depth, motion, state, and component tokens observed or defined in the source.
- Typography: families, weights, sizes, line heights, heading/body/label/caption roles.
- States: loading, empty, error, permission, disabled, hover, focus, selected, success — per component/screen, noting which are missing.
- Responsive behavior: breakpoints, layout shifts, mobile/tablet/desktop rules — or note if not shown.
- Accessibility signals: contrast, focus indicators, touch targets, keyboard/screen-reader hints — or note if not covered.
- Design-system conventions: naming, source-of-truth order, component-to-token mapping, annotation standards present in the source.

### Open Questions And Implementation Dependencies

Surface, do not bury:

- Missing screens, states, or flows the design implies but does not show.
- Ambiguous behavior, copy, validation, or edge cases.
- Token/component gaps that block implementation (undefined tokens, missing variants, no empty/error state).
- Dependencies: backend APIs, data shapes, permissions, analytics events, localization, platform constraints.
- Design-system decisions deferred to engineering.

Rank questions by how much they change scope or sequencing.

### Ticket Shaping Rules

Turn the inventory into a board-ready backlog. These rules are board-agnostic — they apply to Jira, Linear, or any chosen tracker:

- Hierarchy: initiative/epic where the work is broad, then feature, then PR-sized vertical-slice ticket (Feature Granularity).
- Each ticket is one independently grabbable, verifiable slice — a single PR's worth of work where practical.
- Every ticket includes: title, type (Feature, Bug Fix, Chore, Spike — or the board's native types), the user job, acceptance criteria, validation/checks, design-evidence links (Figma frame/preview/screenshots), and dependencies (tokens, components, states, APIs, permissions).
- Reference the exact components, tokens, typography, and states the slice touches from the inventory — do not restate the whole design system per ticket.
- Call out missing prerequisites (token not yet defined, component not built, API pending) as explicit dependencies or a preceding Spike.
- Mark status clearly: PROPOSED (not yet written to the board) vs. CREATED (actually written after approval). Never claim a ticket was created when it was only proposed.

### Board Propagation In PO Mode

All board writes are approval-gated.

- No board or tickets yet: propose the hierarchy and ticket set first (status PROPOSED). Create only after the user approves the structure and target board.
- Tickets already exist: match inventory items to existing tickets, propose updates (links, acceptance criteria, dependencies, status), and apply only after approval. Append, never overwrite history.
- Detect the connected board MCP and use its native actions. Do not assume the board is only Jira or Linear — honor whichever tracker the user selects.

## Propagation: Figma And Board

Propagation differs by mode. All external writes are approval-gated.

- Design-maker mode: after signoff approval, propagate the signed-off UI to BOTH the design source of truth and the ticket board.
- PO mode: propagate the ticket set to the board from the inventory (Ticket Shaping Rules). There is no mockup signoff — the approval gate is the user's go-ahead on the proposed hierarchy and tickets. Figma/source-of-truth writes happen only if the user asks to record the inventory or decisions there.

### To the design source of truth (Figma by default)

- Push the signed-off surface into Figma: frames and screens via the design-generation skill, and components, tokens, and typography via the library-generation skill — loading the matching prerequisite skill before each Figma tool call, exactly as elsewhere in this skill.
- Ensure the feature's Figma home holds its components, design tokens, and typography (Feature Granularity).
- Add annotations covering the same look, behavior, states, and accessibility captured in the signoff. Prefer Figma Code Connect to keep the mockup-to-Figma mapping live.
- If the SoT is not Figma, write the same record into the chosen SoT (Confluence, Notion, Doc, or repo docs): preview screenshots, decisions, tokens, typography, states, and the preview URL.

### To the ticket board (Linear, Jira, or the chosen board/tracker — whichever MCP is connected)

Detect the connected board tool and the target project or board. Do not assume the board is only Jira or Linear — honor whichever tracker the user selects.

- No board, project, or tickets yet: introduce the structure and propose a ticket format before creating anything. Recommend a hierarchy (initiative or epic, then feature, then bug or chore) and classify each unit as Feature, Bug Fix, Chore, or Spike. Give a ready-to-use ticket template: title, type or label, the user job, the Figma link (feature home), the live preview URL, a look-and-behavior summary, states covered, acceptance criteria, and design dependencies (tokens, typography, components). Use the granularity from Feature Granularity. Create tickets only after the user approves the structure.
- Board or tickets already exist: find the ticket that owns the UI piece and update it with the new UI version — refresh the Figma link and preview URL, and post a comment recording that the revision was posted and what changed in that UI piece, linking the signoff, preview, and Figma. Use the board's native comment action (`save_comment` for Linear, `addCommentToJiraIssue` for Jira, or the chosen board's equivalent). Do not silently overwrite history — append the revision note.
- Keep the board layer board-agnostic: same behavior regardless of which tracker is connected.

