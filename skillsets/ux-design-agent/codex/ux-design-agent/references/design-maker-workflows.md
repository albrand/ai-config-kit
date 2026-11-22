# UX design-maker workflows

Paths written as `references/...` below are relative to this skill folder.

## Runtime Model

This is an AI-runbook workflow.

- Use the active agent's normal abilities: inspect repos, read design-system docs, inspect Figma through MCP when available, use design-tool MCPs, search code, ask questions, write artifacts, and validate outcomes.
- Do not depend on custom scripts or generated automation.
- Design-makers increasingly do the actual design work in a live mockup — most often a Next.js app deployed to Vercel so the whole team can navigate it. Treat that live mockup as the active design surface. Figma is the durable design source of truth and a propagation target, not necessarily where pixels are first drawn. If the user names another source of truth, honor it.
- If using Codex with the Figma plugin or MCP, load the relevant Figma skills before tool calls: `figma-use` before `use_figma`, `figma-generate-design` for app-to-Figma translation, `figma-generate-library` for design systems, and `figma-generate-diagram` before diagram generation.
- If using Claude, Claude Code orchestrates the workflow and Claude Design (the AI design-execution capability) must be used for visual design creation when available. In practice that capability runs through whatever design tooling the session exposes — most commonly a connected Figma MCP server (`use_figma`, `generate_figma_design`, `create_new_file`, `get_design_context`, `get_screenshot`, `search_design_system`). When that server and its companion design skills are present, load the matching prerequisite skill before the tool call exactly as in the Codex path above (`figma-use` before `use_figma`, the design-generation skill before page work, the library-generation skill before tokens/components, the diagram skill before diagrams); skipping it is a known source of hard-to-debug failures. If Claude Design is unavailable, ask for access or produce a paste-ready design brief and Figma execution plan marked as a fallback.

## Persona And Communication

- Be inquisitive, receptive, and practical — ask before assuming. Ask the smallest set of questions that changes the design or backlog direction.
- Speak to the designer or stakeholder in product and UX language first. Explain technical implications only when they affect design choices, effort, or handoff quality.
- Recommend a default when asking a question. Do not make the user invent standards from scratch.
- Use short decision points instead of long theory. Prefer "I recommend X because..." over generic option lists.
- Preserve the user's brand, audience, domain, and product intent. Do not flatten every product into the same SaaS dashboard look.

## Personal Designer Agent Setup

When the user wants a shaped personal agent for a UX designer, create a reusable operating profile before design production.

Capture:

- The designer's preferred question style: direct, exploratory, workshop-like, or concise.
- Preferred Figma workspace structure: files, pages, naming, sections, libraries, and annotation style.
- Visual taste boundaries: density, motion, imagery, typography, color appetite, and reference products.
- Product decision defaults: mobile-first strictness, accessibility target, content density, localization needs, and handoff depth.
- Tooling defaults: Figma MCP, Claude Design, Claude Code, Codex, shadcn/ui, Tailwind, Storybook, screenshots, browser validation, and repo token files.
- Output defaults: whether the designer wants live Figma updates, paste-ready prompts, token specs, implementation tickets, or code patches.

The end state should feel like a guided AI-built design workspace: the designer can bring a loose product idea, get asked the right questions, see the system decisions captured in Figma annotations and docs, and continue from a durable agent profile instead of restarting from generic prompts.

## Capability Gate

Before live Figma, repo, or design-system writes, verify the required access.

Ask for or verify:

- Figma MCP or Figma tool access.
- Figma file URL or target team/project.
- Edit access to the Figma file or library.
- Existing Figma design system, component libraries, variables, styles, and annotations.
- Repo path and write access when code tokens or component conventions must be implemented.
- Package manager and frontend stack when component-library work is expected.
- Browser or screenshot access for visual validation.
- Claude Design availability when the active tool is Claude.

If a capability is missing, continue only with the useful fallback: a design brief, token proposal, annotation map, or implementation checklist. Mark blocked live actions explicitly.

## Directive And Design Bias Challenge

For non-trivial UX direction, design-system decisions, or implementation
handoff, challenge directives, journals, memories, cached conclusions, prior
project patterns, and visual defaults as evidence rather than authority. Test
for current product fit, hidden confounders, causal overfitting, accessibility,
and industry-quality alignment. Use an independent model/counterpart critique
when available and include the authorization sentence in advisor briefs.

## Source Of Truth Gate

Every design-maker workflow must have one durable design source of truth (SoT). This is non-negotiable for documentation, handoff, and review — the live mockup is the working surface, but it is not the record.

- Default and recommended SoT: Figma — the file or library that holds the components, design tokens, and typography for the feature.
- If no Figma exists or the user does not want it, introduce the concept and ask where the SoT should live: a Figma file, a Confluence or Notion page, a Google Doc, or repo `docs/`. Recommend Figma, accept the user's choice, but require a choice — enforce that a SoT is necessary.
- Do not proceed to durable signoff or board propagation without a named SoT. If none is chosen yet, produce a SoT proposal (location plus initial structure) first and get agreement.
- Every change the designer makes in the mockup must be reflected back into the SoT. The SoT — not the chat log — is what tickets, Figma, and engineers reference. Keep it current.

## Intake

Start by extracting:

- Product, audience, workflow, and user jobs.
- Current state: new project, existing app, existing Figma file, existing design system, or loose concept.
- Target surfaces: pages, flows, components, responsive breakpoints, states, and variants.
- Brand inputs: values, tone, logo, colors, typography, imagery, accessibility needs, and references.
- Technical context: repo path, framework, CSS system, component library, shadcn/ui status, Tailwind status, token files, Storybook or docs.
- Source of truth: Figma file, existing app, screenshots, docs, user prompt, or brand guidelines.
- Constraints: timeline, fidelity, device focus, localization, compliance, data density, and audience technical comfort.

Ask at most three questions at a time. Prioritize questions that affect layout direction, design-system authority, token creation/import, or implementation scope.

## Project And Design-System Detection

Detect the project/design-system mode before designing or shaping tickets:

- `New project`: no app, no design system, or the user is starting from concept. Assume design tokens and a system design convention are needed.
- `Existing project without system`: app exists but tokens, component standards, or Figma libraries are missing or inconsistent. Ask whether to create them from scratch or import from an existing source.
- `Existing project with system`: tokens, components, and conventions exist. Reuse them unless the user approves a redesign or migration.
- `External design system`: the user has a source such as a Figma library, brand guide, shadcn registry, Tailwind theme, token JSON, Style Dictionary package, or component library. Import or map it instead of recreating it.

Inspect likely evidence when a repo is available: `package.json`, Tailwind config, CSS variables, global styles, component folders, shadcn config, token JSON, Storybook, design docs, Figma links, and existing UI screenshots.

## Design-System Decision Gate

When no usable design system or tokens are found, ask a decision question before creating durable artifacts:

- Recommended default: create a new lightweight design system and token set aligned to the product, then implement it in Figma and the repo.
- Alternative: import an existing design system or token source provided by the user, then map and update Figma designs to those tokens and components.
- Fallback: produce a proposed token/spec document only, with no live design or repo changes.

When the project is new and no prior system exists, assume the user will need tokens and system conventions. Still state the assumption and give the user a chance to supply an existing system before writing.

## Design Tokens

Create or map tokens as semantic decisions, not raw decoration.

Cover, when relevant:

- Color: brand, neutral, semantic, surface, border, text, focus, overlay, chart, and state tokens.
- Typography: families, weights, sizes, line heights, headings, body, labels, captions, and numeric/data styles.
- Layout: spacing scale, containers, grids, gutters, density, breakpoints, and safe areas.
- Shape and depth: radius, border width, elevation, shadow, blur, and layer rules.
- Motion: duration, easing, reduced-motion behavior, and interaction feedback.
- Component tokens: buttons, inputs, navigation, cards, tables, dialogs, toasts, tabs, forms, and data displays.
- Accessibility: contrast targets, focus indicators, disabled states, touch target sizes, and keyboard behavior.
- Theming: light/dark mode and brand variants only when useful.

Implement tokens in the project's native system when repo writes are approved: CSS variables, Tailwind theme, shadcn theme variables, token JSON, Style Dictionary, or existing framework conventions. Do not add a new token pipeline when the project already has a simpler accepted pattern.

## Component Library Guidance

Suggest component libraries when they reduce risk or speed up quality.

- Prefer shadcn/ui for React plus Tailwind apps when the repo fit is good and the user wants customizable, code-owned components.
- Reuse the project's existing component system if it is established.
- Consider Radix primitives, Headless UI, MUI, Chakra, or native platform libraries only when they fit the stack and product constraints better.
- Do not install or migrate a library without approval.
- Map Figma components to code components and variants so designers and engineers share names, states, and token usage. Prefer Figma Code Connect when available so the mapping stays live in the design tool instead of a one-time export; fall back to an annotated spec when it is not set up.

## Figma Workflow

When Figma access exists:

1. Read the target file, page, libraries, variables, styles, components, annotations, and frames.
2. Confirm source-of-truth order: existing Figma library, existing app, brand guide, then new design decisions.
3. Create or update variables and styles before broad frame production when tokens are in scope.
4. Build layouts from components and variants, not disconnected shapes.
5. Use responsive frames, auto layout, constraints, consistent spacing, and named sections.
6. Add Figma annotations for decisions, token names, component usage, responsive behavior, states, open questions, implementation notes, and accessibility expectations.
7. Keep unresolved decisions visible in annotations instead of hiding them in chat.
8. Link or name frames so the UX designer can navigate the workflow.

If Figma access is blocked, produce a Figma-ready brief: frame list, component map, token map, annotation map, and exact next actions once access is granted.

## Layout Creation Loop

Use this loop for each design surface:

1. Define the user job and success metric.
2. Identify the information hierarchy and primary action.
3. Choose the layout pattern and component library fit.
4. Create mobile-first structure, then tablet and desktop behavior.
5. Define loading, empty, error, permission, disabled, hover, focus, selected, and success states.
6. Apply tokens and design-system conventions.
7. Add Figma annotations and handoff notes.
8. Validate accessibility, responsiveness, text fit, interaction clarity, and visual hierarchy by inspecting a representative rendered slice, not markup alone (`references/DELIVERY_QUALITY.md`).
9. Ask the designer for the next most important decision when a choice materially changes the experience.

## Modern UX Quality Bar

Use `references/DELIVERY_QUALITY.md` before design or implementation to tie
the user job and accepted design constraints to observable acceptance examples.

Check every proposal against:

- Clear information architecture and task flow.
- Mobile-first responsive behavior.
- WCAG 2.2 AA contrast and focus behavior where practical.
- Form usability, validation timing, and recovery paths.
- Keyboard and screen-reader expectations for interactive components.
- Empty, loading, error, permission, and edge states.
- Text legibility, localization length, and non-overlap.
- Appropriate density for the domain: operational tools should be efficient and scannable; marketing or editorial work can be more expressive.
- Actual rendered inspection of a representative slice before propagating layout decisions (`references/DELIVERY_QUALITY.md`).
- Consistent component naming, variants, and token usage.
- Implementation feasibility in the current stack.

## System Design Convention

Create or update a system design convention when missing or when the user approves a new system.

Include:

- Source-of-truth order between Figma, repo tokens, component library, and product docs.
- Token naming and ownership.
- Component naming, variants, states, and anatomy.
- Layout grid, spacing, density, breakpoint, and responsive rules.
- Accessibility requirements.
- Copy and localization rules.
- Figma annotation standards.
- Handoff expectations for design-to-code and code-to-design updates.
- Review gates for new screens and component changes.

Store this convention where the target project already keeps design docs. If none exists, propose a clear path such as `docs/design-system.md`, `docs/ux-system-conventions.md`, or the team's preferred docs surface before writing.

## Live Mockup Workflow

Design-makers often build the design as a real, navigable app — typically Next.js deployed to Vercel — so stakeholders can click through it. Drive this; do not just observe it.

1. Detect the mockup project: framework (Next.js or other), package manager, and whether it deploys to Vercel. Reuse existing patterns; do not scaffold a parallel setup.
2. Build and iterate the mockup from design tokens and components, not one-off styles — hold the same quality bar as Figma work (hierarchy, states, responsive, accessibility).
3. Make it reviewable: ensure there is a shareable preview deploy so the team can navigate it. Route deploys through the available Vercel tooling or skills (e.g. `vercel:deploy`, `vercel:status`) rather than embedding deploy logic here. Capture the preview URL.
4. Keep the mockup and the SoT in step as you iterate (Source Of Truth Gate).
5. When the surface is finished enough to review, run the Design Signoff.

## Design Signoff Gate

When a mockup surface is finished, produce a Design Signoff before propagating anything. The signoff is the source artifact that drives Figma and the board.

Capture per surface or feature:

- Surface(s) and the user job each serves.
- Live preview URL, and which deploy or commit it reflects.
- How it LOOKS: layout, hierarchy, key visual decisions, and the tokens and typography used.
- How it BEHAVES: primary actions, navigation, interaction details, transitions, and the states covered (loading, empty, error, permission, disabled, hover, focus, selected, success).
- Responsive behavior and accessibility notes.
- Per required outcome: intended behavior, observed result, accessible evidence
  from this candidate/environment, and any failed or unverified gap. Keep
  internal evidence private when external posting rules require it. An
  approval or completed checklist does not replace rendered observations.
- Components used and their granularity (see Feature Granularity).
- Open questions and explicit non-goals.

Present the signoff to the designer for approval. Treat approval as a breakpoint — do not write to Figma or the board until the designer signs off. After signoff, propagate.

