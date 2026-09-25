---
name: verified-qa-e2e
description: >
  Use before writing, replacing, or publishing QA instructions in Jira, Linear,
  or another tracker; before moving work to Ready for QA or calling interface
  end-to-end testing complete or blocked; and whenever a tester journey depends on login,
  seeded accounts, role-specific portals, generated links, tokens, permissions,
  or test data. Prevents plausible instructions from being published for the
  wrong persona, wrong product surface, or an unreachable workflow.
verify: 'node "$HOME/.agents/skills/verified-qa-e2e/scripts/qa-e2e-gate.mjs" selftest'
verified: 2026-09-25
---

# Verified QA and interface E2E

This skill is an authorization and completion gate. A readable checklist is
harmful when the intended tester cannot reach its first step, and a real button
name is still false evidence when it came from a different persona or product
surface.

Reasoning effort may change exploration depth, latency, and cost. It never
changes this evidence contract, its allowed terminal states, or permission to
publish. There is no low-effort bypass and no high-effort exception.

## Load the right source of truth

Use current evidence in this order:

1. The target environment as the intended tester persona.
2. The authoritative ticket and accepted behavior.
3. Repository-owned setup, seed, role, and test-data documentation.
4. Current code and tests as supporting evidence.
5. Prior comments, memory, designs, or inferred routes only as leads.

Code, old screenshots, another tenant, or another persona cannot prove that a
control is currently reachable.

## Evidence state machine

Advance in order. Do not draft or publish early and validate afterward.

1. `ACTOR_VERIFIED`
   - Name the tester persona, target environment, and exact product surface.
   - Keep administrator, operations, vendor, customer, member, and reviewer
     experiences separate.
2. `ENTRYPOINT_VERIFIED`
   - Reach the exact starting page through a current authorized route.
   - A URL pattern, source route, or remembered menu path is not enough.
3. `AUTHENTICATION_RESOLVED`
   - A logged-out screen is state, not automatically a blocker.
   - Before requesting user interaction, inspect repository-owned seed/setup
     material for authorized test identities and roles. Attempt the applicable
     identity without printing, copying, or journaling credentials.
   - Before walking with a discovered identity, check whether an automated
     suite owns it: it appears in CI workflows or in e2e setup, fixtures or
     teardown that create, reset or delete its data. Use an identity no suite
     owns. On 2026-09-25 two interactive walks on meu-psi signed in as the
     deployed CI suite's own e2e identities on the shared preview DB. The
     suite's setup recreated their data mid-walk, the walks changed data under
     the suite, and its gate went 36/38 on a build that was 38/38 twelve
     minutes earlier. Both sides' evidence was contaminated.
   - If the repository has no unowned identity, walk with the owned one only
     outside every automated run on the same data. After the walk, check for
     runs whose interval intersected the walk window (a check at the start
     would have passed the meu-psi incident), and say in the evidence that the
     identity is shared. A run that overlapped makes the walk invalid: record
     an `environment_contamination` defect naming the writer and walk again.
     Record all of it in `authentication.identity`
     (`references/evidence-contract.md`).

   - If no repository identity exists or it cannot work in the target
     environment, record the discovery evidence before classifying auth blocked.
4. `PREREQUISITES_AVAILABLE`
   - Prove every required link, token, permission, role, test record, and timing
     condition is obtainable by the intended tester.
   - When a prerequisite appears missing, inspect the current screen and follow
     its visible setup or connection path as this persona would. Check the
     effect and authorization before actions that grant access or affect live
     data. Record the control used and the result; a fixture or source search
     cannot replace an authorized UI attempt.
   - If that path needs user consent or a sign-in, obtain the applicable
     browser takeover approval and resume the same journey afterward. Use the
     manual-login gate only when its logged-out conditions match. Pending
     consent is not a final blocker.
     Never infer consent for email access from permission to test; never open a
     compose surface or send a message without approval for that message.
   - Engineering-prepared data may be a prerequisite, but do not turn its setup
     into a technical QA step.
5. `FLOW_WALKED`
   - Walk the requested journey on the same persona, environment, and surface.
   - Capture page titles, menu names, buttons, visible states, and expected
     results from that walk. A visible label counts only on the intended surface.
6. `DRAFTED`
   - Write concise screen actions and visible expected results from the captured
     evidence. Keep internal validation provenance out of the external comment.
7. `PUBLISHED`
   - Publish only when the external mutation is authorized, the draft was
     previewed, and the bundled gate passes.

## Deterministic gate

Create a private evidence JSON file without secrets, cookies, or tokens. Use the
shape in `references/evidence-contract.md`, then run:

```sh
node <this-skill-directory>/scripts/qa-e2e-gate.mjs check <evidence.json>
```

The gate supports `publish_qa_instructions`, `claim_e2e_complete`,
`claim_e2e_blocked`, and `request_manual_browser_login`. Run
`claim_e2e_blocked` before calling a reached prerequisite a blocker. Exit zero
authorizes that exact claim and
nothing broader. A passing `request_manual_browser_login` authorizes only the
interim manual-login handoff; it is never a PASSED E2E state and never
authorizes publication or a completion claim. A non-zero result lists missing
evidence and blocks it. If the script is missing or cannot run, report `QA/E2E
guard unavailable`; do not publish QA instructions or claim the interface journey is
complete.

The evidence packet remains private. External Jira, Linear, pull-request, or
release content contains only the authorized QA actions/results, product status,
decision, or blocker—not commands, test counts, model names, or internal
validation provenance.

## Allowed terminal states

- `PASSED`: the requested journey was walked and the gate passed.
- `FAILED`: the intended journey reached a reproducible product failure with
  evidence from the correct actor and surface.
- `BLOCKED`: the first missing prerequisite is named and the relevant discovery
  paths were exhausted, including the visible user path. A pending request for
  permission or login is an interim state; resume after the response. A product
  control that fails is `FAILED`, even when the defect predates this change.
  Do not publish executable QA steps for a blocked flow.

Encountering friction, reaching a login page, drafting a plausible checklist,
or successfully updating the tracker is not completion.

## Browser instance lifecycle

Treat an interactive browser instance as one bounded resource owned by the
current thread, not as a disposable preamble to every browser action.

- Enumerate instances before the first browser action. Reuse the one owned by
  this thread; never target an unowned or other-thread instance.
- Ordinary navigation, snapshot, click, wait, and flow tools acquire or reuse
  the thread instance automatically. Do not call `browser_open` before them.
  Use `browser_open` only when the browser adapter requires an explicit
  isolated cookie jar or label and the thread owns no instance yet.
- A thread may own one instance at a time. To change cookie isolation, close
  the owned instance first and then create its replacement; a second instance
  is not a focus, retry, or navigation mechanism.
- Close the owned instance when the bounded browser slice passes, fails, is
  blocked, abandoned, or superseded. Preserve it only when a declared immediate
  follow-up, such as an authorized manual-login handoff, needs the same tab.
- Listing, refreshing, releasing, or closing an instance must never create a
  replacement tab. If the adapter does that, stop and report a browser lifecycle
  defect rather than retrying.

## Manual browser login handoff

When authentication requires the user to sign in manually in a browser the
agent controls, treat the handoff as a guarded interim operation, not as
progress toward completion. Before the gate can authorize
`request_manual_browser_login`, actor and entrypoint evidence must already
exist, authentication must be required, both initial and current authentication
state must be `logged_out`, repository test identity discovery must have run
(with separate attempt evidence for any discovered identity), and
evidence must show why manual interaction is necessary. The `manual_login`
contract in `references/evidence-contract.md` then binds the request to one
concrete browser instance.

Runtime behavior, provider-neutral:

- Enumerate browser instances first (`browser_instances` or the platform
  equivalent). Reuse the single instance the current thread already owns. If
  it owns none, open exactly one; never create another to solve focus.
- Close only duplicate instances this thread created and owns. Never close
  unknown, user-owned, pre-existing, or other-agent tabs; report them instead.
- Repeatedly calling `browser_open` is not a focus strategy. It multiplies
  tabs in a shared window and is the recorded failure mode this gate exists to
  prevent.
- A takeover/control grant on a shared Chrome window exposes every tab in that
  window and cannot prove the target tab is foregrounded. Never call it a
  dedicated tab or window, and never state the exact login page is open unless
  adapter evidence proves it. Disclose the exposed tab count and the observed
  target title.
- Never type, paste, fill, or otherwise handle credentials, even when the user
  offers them. The user performs the sign-in.
- After sign-in, release the instance, then verify the authenticated state
  headlessly through a snapshot bound to the same instance before continuing
  the journey.
- Stop and report when a bot challenge appears, the user declines or times
  out, or a snapshot contradicts the assumed state.

The evidence packet is self-attested JSON. It checks required evidence shape
and ordering only; it cannot prove runtime ownership or authorization. Adapter
control-plane and tool evidence remain authoritative over any packet claim.

For `publish_qa_instructions` or `claim_e2e_complete` packets that include
`manual_login`, the gate additionally requires a post-login snapshot bound to
the same instance with `authenticated_state_observed` and evidence, plus
`released: true`, and rejects inconsistent instance IDs.

## Recovery after a bad publication

Stop further mutations. Re-run the state machine from the intended actor and
surface, identify every affected external comment, and prepare the smallest
correction. Replace or mark obsolete content only when that mutation is
authorized. Do not compound the error with another unverified checklist.
