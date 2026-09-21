# Proposal — typed decision primitives (from TypeSafe Jev) — 2026-09-21

**Status: items 1–3 applied 2026-09-21. Item 4 waits until the gates see
real use. Item 5 needs the owner's decision.**

Applied as:

- the `typed-decisions` shared skill, published to every agent home, local
  and VPS;
- an always-on block in every global instruction file;
- a "Typed decisions here" block in each decision-owning skill
  (meaningful-tests, finish-the-job, scope-advisor, reviewing-with-an-agent,
  delegating-to-glm, high-signal-pr-review and `/code-review`,
  adversarial-security-sweep, plan-arbiter, hermes-assisted-pr-review,
  harness-routing);
- the typed-decision amendment in TOKEN_EFFICIENT_ORCHESTRATION protocol 1;
- `scripts/typed-decisions-sync.py --check --falsify`, run daily by the
  agent-hooks checks.

`issue-triage-state-machine` has no skill file yet, so the triage rule lives
in the `typed-decisions` skill only.

## Source

TypeSafe AI's Jev is a "System One" model. It never generates text. It takes
*state + typed questions* and returns an answer from a fixed answer space, with
a probability distribution and a confidence value, in one parallel pass.
Three primitives:

| Primitive | Asks | Returns |
| --- | --- | --- |
| Noul | "Is this statement true?" | p(true) 0–1 |
| Choice | "Pick one of N options" (≤255) | option, per-option probs, confidence |
| Score | "Place on a 2–10 level rubric" | level, distribution, confidence |

Sources: docs.typesafe.ai/introduction; the LangChain harness write-up
(Jev as a pre-LLM classifier and a tool-call guard); the community reference
gist (pjburnhill). Vendor speed/cost claims (100–400x) are not relevant here.

## What transfers (the method, not the model)

1. **Decide vs create.** Most agent steps are decisions: route, triage, "is
   this in scope", "is this risky", "is this done". Those need a typed answer.
   Only generation needs prose. The kit treats both the same way today.
2. **Closed answer spaces.** A decision comes from an enum declared in
   advance, never from free text. An answer outside the enum is invalid, not
   something to interpret.
3. **Atomic questions.** One judgment per question, something an expert could
   answer in seconds. Deterministic code combines the answers. Nobody asks
   "is this PR ready?"; they ask "tests touched? auth touched? scope matches
   ticket?" and code computes readiness.
4. **Isolated evaluation against the same state.** Each question sees the same
   state, never the other questions' answers. This is the same idea as the
   kit's blind finders and independent verifiers, applied to single decisions.
   It stops anchoring, and it stops a long review thread's context from
   degrading ("context rot").
5. **Confidence-gated action.** High confidence: automate. Medium: verify.
   Low: escalate to a reasoning model or a human. Human-set thresholds fix
   where each tier starts.
6. **Type-safe ≠ correct.** A well-formed answer can still be confidently
   wrong. Calibration holds across a group of answers, not for any single
   one. So thresholds must be checked against real outcomes, not asserted.
7. **Suitability test** before building a decision point: deciding rather
   than creating? Answer space known? One atomic judgment? State fits? Could an
   expert decide in seconds? Consumed directly by software? 5–6 yes → use a
   typed decision.

## The trap to avoid

Jev's confidence is *trained* to be calibrated. An LLM's self-reported
"confidence: high" is not: verbalized confidence is known to be poorly
calibrated. Copying the confidence-gate shape onto self-reports would give us
another installed-but-inert control. In the kit, confidence must come from one of:

- **Agreement:** N isolated evaluations of the same question (the "blind
  finder" pattern), where confidence = share that agree;
- **Evidence:** a measurable check that settles the question (file state,
  test result, exit plus target-state read);
- **Track record:** the outcomes ledger for that decision point, once it
  exists (see 4 below).

## Proposed changes

1. **New skill `typed-decisions`** (global catalog row + `skillsets/` entry):
   the suitability test; the three primitive shapes (yes/no, pick-one,
   ordinal rubric with written level descriptions); atomic decomposition with
   composition in code; the isolation rule; the three-tier gate with confidence
   sourced only from the three sources above. Expected output: a decision spec
   (question, answer space, state, confidence source, tier thresholds,
   escalation target).
2. **Apply it to existing decision points first.** No new machinery:
   - `issue-triage-state-machine`: already an enum (Choice). Add the tier gate:
     `ready-for-agent` only on agreement or evidence, otherwise `needs-info`.
   - `high-signal-pr-review` / `adversarial-security-sweep`: severity becomes a
     Score with written level anchors. The refute pass becomes a Noul per
     finding ("does this reproduce on the changed path?"), checked in isolation.
   - `scope-advisor`: verdict is already Choice (aligned/revise/clarification).
     Split into atomic Nouls per requirement (covered? added-unrequested?)
     and compose in code.
   - `harness-routing` / `bb fleet route`: route category is a Choice. Add a
     low-confidence path that escalates to the architecture lane instead of a
     silent default.
   - Directive-challenge risk triggers (CLAUDE.md step 7): make each trigger a
     Noul (touches auth? irreversible? unexplained failure?). Then "should a
     counterpart run" is computed from those answers, not re-judged in prose.
3. **Delegate contract extension** to TOKEN_EFFICIENT_ORCHESTRATION rule 2.
   When a delegate's job is a decision, it returns
   `{question, answer ∈ declared space, evidence, confidence_source}`. An
   out-of-space answer counts as a failed delegate, not an input to interpret.
4. **Outcomes ledger (later, only if 1–3 get used).** Log each gated decision
   and its eventual truth, e.g. finding confirmed or refuted, or triage
   bounced back. This is the only honest way to set thresholds. Until it
   exists, thresholds are human-set and labelled as such.
5. **Optional experiment, needs your call:** use Jev itself as a cheap guard
   in hooks (context-hygiene classification, tool-call risk checks, like
   LangChain's AutoModeMiddleware). This needs an API account and sends
   hook state to an external service, which the kit's MCP/external-service
   routing rules gate. Not proposed for adoption without that decision.

## Non-goals

- No Jev dependency in the kit.
- No LLM-self-reported confidence as a gate, anywhere.
- No rewrite of existing skills beyond the decision points listed in 2.
