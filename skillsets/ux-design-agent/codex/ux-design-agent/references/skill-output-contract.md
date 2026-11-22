# UX design-agent output contract

Paths written as `references/...` below are relative to this skill folder.

## Output Contract

For complex work, read `references/output-contract.md` before the final report.

Return:

- Skill mode: design-maker or prototype-consumption/backlog-shaping (PO), detected and announced.
- Design-maker detection (when design-maker mode): detected and announced, or deferred with reason.
- Personal designer-agent profile created or updated when requested.
- Project mode: new project, existing without system, existing with system, or external design system.
- Capabilities verified, missing, and fallback used.
- Source of truth: location chosen, enforced, and kept current.
- Questions asked and recommended defaults.
- Token decision: created, imported, mapped, proposed, or blocked.
- System convention decision: created, updated, proposed, or blocked.
- Component library recommendation and rationale.
- Live mockup status (design-maker mode): framework, preview URL, and Vercel deploy state.
- Design signoff (design-maker mode): approved, pending, or per-surface, with what it covers.
- Design inventory (PO mode): screens/flows, components, tokens, typography, states, responsive, accessibility, design-system conventions — with evidence and gaps.
- Open questions and implementation dependencies (PO mode), ranked by scope/sequencing impact.
- Ticket set (PO mode): hierarchy, PR-sized slices with acceptance criteria and design-evidence links; status PROPOSED vs. CREATED for each.
- Figma (or chosen SoT) propagation: work completed or planned, including annotation coverage.
- Board propagation: tool (Linear, Jira, or the chosen board/tracker), tickets created or updated, comments posted, or ticket format proposed.
- Repo/design artifacts changed or proposed.
- UX validation performed with evidence bound to the candidate version and environment (`references/DELIVERY_QUALITY.md`), and residual risks.

