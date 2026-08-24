---
name: verified-qa-e2e
description: >
  Use before writing, replacing, or publishing QA instructions in Jira, Linear,
  or another tracker; before moving work to Ready for QA or calling interface
  end-to-end testing complete; and whenever a tester journey depends on login,
  seeded accounts, role-specific portals, generated links, tokens, permissions,
  or test data. Prevents plausible instructions from being published for the
  wrong persona, wrong product surface, or an unreachable workflow.
verify: 'node "$HOME/.agents/skills/verified-qa-e2e/scripts/qa-e2e-gate.mjs" selftest'
verified: 2026-08-24
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
   - If no repository identity exists or it cannot work in the target
     environment, record the discovery evidence before classifying auth blocked.
4. `PREREQUISITES_AVAILABLE`
   - Prove every required link, token, permission, role, test record, and timing
     condition is obtainable by the intended tester.
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

The gate supports `publish_qa_instructions` and `claim_e2e_complete`. Exit zero
authorizes that exact action. A non-zero result lists missing evidence and
blocks it. If the script is missing or cannot run, report `QA/E2E guard
unavailable`; do not publish QA instructions or claim the interface journey is
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
  paths were exhausted. Do not publish executable QA steps for a blocked flow.

Encountering friction, reaching a login page, drafting a plausible checklist,
or successfully updating the tracker is not completion.

## Recovery after a bad publication

Stop further mutations. Re-run the state machine from the intended actor and
surface, identify every affected external comment, and prepare the smallest
correction. Replace or mark obsolete content only when that mutation is
authorized. Do not compound the error with another unverified checklist.
