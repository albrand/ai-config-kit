# Delivery Quality

Canonical doctrine for first-delivery correctness: useful tests, expected
behavior, UI/UX creation and verification, and honest completion claims.

Route here before selecting test evidence, shipping behavior, or designing or
reviewing UI. In full framework installs, `TEST_OWNERSHIP.md` owns detailed
boundary choices; standalone skills can apply this protocol directly. It
defines useful evidence and the claims that evidence supports. Copies in the core-framework, ux-design-agent, and
ux-design-intelligence skillsets must stay byte-identical to this file.

Core rule: more tests, higher coverage numbers, self-scores, model agreement,
or a filled evidence form are not correctness. Evidence counts only when it
can fail for the right reason on the delivered candidate.

Scale the work to the change. Reuse existing acceptance criteria and evidence;
a small spacing fix can need only direct rendered inspection and an affected
neighbor check. No new suite, artifact template, design system, deployment, or
review round is required merely to fill this protocol.

## 1. Acceptance Examples Before Implementation

Before implementing, derive compact acceptance examples from the complete
request and authoritative task evidence (ticket, spec, design, board
criteria):

- Actor and context, starting state, action.
- Observable expected result derived from the request, not copied from the
  implementation or its current output.
- Important failure and edge behavior.
- Protected adjacent behavior that must not regress.

Use context already in hand before asking a material question; scope already
authorized needs no extra approval. Scale detail to risk, reuse existing
acceptance criteria, and do not chase a checklist-count quota.

## 2. Useful Test Evidence

For each new or changed check, name the concrete owned failure it catches. If
no plausible failure exists, the check is ceremony, not evidence.

- Exercise production entrypoints. Assert observable output and state, not
  callback counts or private internals alone.
- Distinguish a controlled external dependency from a mock that replaces
  behavior the repository owns. A mocked handler plus a green test proves the
  fixture contract, not the product.
- Prefer the cheapest boundary that owns the truth, and reuse existing checks
  when they are enough. No blanket mutation suites, no coverage-percentage
  targets.
- Defect check: for a bug regression, run the focused check against the
  pre-fix version and demonstrate the behavioral failure. If impractical, record the
  specific reason and run a bounded, reversible substitute on the changed
  critical assertions - bad input, disabled effect, injected fault, or
  targeted mutation - or record the gap as unverified.
- Report unperformed falsification honestly. A test that survives the defect
  provides no evidence for that claim, and an import or setup failure is not
  a behavioral red.
- Persistence claims require a write followed by a real readback or reload at
  the owning boundary. A success toast plus a mocked 200 proves only the mock.

Example: a settings form shows "Saved" and its tests pass against a mocked
API, but nothing persisted. Useful evidence saves, then reloads or re-queries
through the real boundary and asserts the stored value.

## 3. UI Creation

Before drawing, state the user job, the primary action, the accepted
reference or brand, and the supported devices and states.

- Use existing tokens and components; preserve the existing design source and
  accepted decisions.
- Available components are options, not requirements. Include only fields,
  controls and actions supported by the request or existing product evidence.
  Mark additional ideas as optional proposals; do not silently invent data
  fields, filters, priorities or backend capabilities in the design brief.
- Derive focus and selection from the interaction's semantics. Preserve user
  focus and context; do not imply a row is selected or move focus merely to
  make an initial screen look active.
- Use realistic content and data density; make hierarchy, typography,
  spacing, and affordances deliberate; design error recovery and continuity,
  not only the happy path.
- Use `ui-ux-pro-max` only for focused, unresolved design decisions, never as
  a redesign of an authoritative system.
- For substantial design work, inspect a representative rendered slice
  internally before propagating layout decisions. Do not force a Figma,
  deploy, or board approval loop for ordinary fixes.
- Repeated scope or acceptance misses require an independent read-only review
  of the actual proposal and evidence before progressing. Resolve its concrete
  findings; escalate a lane that cannot meet the criteria. Use
  `scope-advisor` when available for scope questions. Do not lower the target,
  add more retries, or count reviewer agreement as rendered/user evidence.

## 4. UI Verification

- Verify on the actual supported runtime, not only in markup or story files.
- Cover the primary user flow including a meaningful result, plus a relevant
  failure/recovery or adjacent regression case.
- Check representative target widths and long, empty, and dense data as the
  change implicates them.
- Inspect the actual screenshot visually, with DOM geometry and interaction
  evidence as needed. Text existence cannot prove visible layout; chart marks
  need meaningful geometry (allow legitimate zero/empty data); links and filters must change the actual
  outcome; focus and keyboard behavior need their own evidence.
- Check clipping, overlays, and readability; screenshot-file existence proves
  nothing.
- Missing image or browser access limits visual claims; static review remains
  useful but is insufficient for visual-quality claims.
- Bind screenshots, checks, and observations to the actual candidate version
  and environment, and replace stale evidence for affected paths after edits.
- Automated checks or model taste never produce a full accessibility or
  human-usability claim.
- If an observation exposes a defect, fix it within scope and repeat the
  affected checks before claiming completion; do not merely attach evidence.

Example: a chart title present in the DOM does not show a rendered chart.
Useful evidence: canvas or SVG geometry at the tested viewport, visible marks,
and a legend interaction that changes what is displayed.

## 5. Completion Claims

- Keep a compact record: `required outcome -> observed result -> evidence ->
  candidate/environment -> limitation`. Use existing handoff/check fields or
  a short paragraph; share repeated context once. Map every required outcome,
  including failed, blocked, skipped, and not-run outcomes, to this record.
- Keep evidence references accessible to the receiving coordinator. Keep the map private
  when posting rules require it; it does not belong in PR surfaces.
- Functional, integration, visual, usability, deployed, and accepted are
  distinct states; report the one that is true.
- Diagnose flaky or infrastructure failures; never change expectations,
  retries, mocks, or snapshot baselines solely to pass.
- Existing gates remain, including the adopted `verified-qa-e2e` gate for its
  exact supported actions; a filled form does not authenticate observations.
- Numeric quality scores may rank improvements; they never make a missing or
  failing required outcome pass.
- Track first-pass acceptance, reopens, or escaped failures only on a defined
  observed sample. Never invent success rates.

## 6. Returned Defects

After a returned defect, reproduce it, add useful owned regression protection
or correct the verification method, then repeat the original acceptance check
plus the affected neighbor. Avoid ritual reruns and unrelated cleanup.

## Sources

Rationale, not authority:

- [Testing Library guiding principles](https://testing-library.com/docs/guiding-principles/): tests resemble how the product is used.
- [Playwright best practices](https://playwright.dev/docs/best-practices): user-visible behavior and awaited assertions.
- [Google Testing Blog on mutation testing](https://testing.googleblog.com/2021/04/mutation-testing.html): targeted faults assess test effectiveness; avoid redundant work.
- [W3C WAI evaluation guidance](https://www.w3.org/WAI/test-evaluate/): automated checks alone cannot establish accessibility.
- [Nielsen Norman usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/): judge feedback, consistency, error prevention and recovery.
