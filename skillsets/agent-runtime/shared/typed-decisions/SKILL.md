---
name: typed-decisions
description: >
  Use whenever an agent step is a DECISION rather than writing — routing, triage,
  in scope or not, risky or not, severity, pass/fail, done or not, escalate or
  not, which model or lane, whether a finding is real. Also use when designing a
  gate, a verdict, a review outcome, a delegate's return contract, or a hook
  that allows or blocks. Makes the answer typed, atomic, independently judged,
  and gated on confidence that was measured rather than claimed.
verify: "test -n \"$HOME\""
verified: 2026-09-21
---

# Typed decisions

Adapted from TypeSafe AI's "System One" model, Jev. Jev never generates text:
it takes *state + typed questions* and returns an answer from a fixed answer
space, with a probability, in one pass. We take the method, not the model.

Most agent steps are not writing. They are decisions: route this, is this in
scope, is this risky, does this finding reproduce, is this done. Handled as
prose, a decision can't be tested, can't be composed, and can't be gated. Its
"confidence" is a word the model chose.

## 1. Is this a decision? (run first)

Answer each yes/no. 5–6 yes → treat it as a typed decision. 3 or fewer → it is
generation; write normally.

1. Is the agent deciding rather than creating?
2. Can the answer space be listed in advance?
3. Is it one atomic judgment?
4. Does the needed state fit in front of the judge?
5. Could an expert answer it in seconds?
6. Will code, a gate, or the next step consume the answer directly?

## 2. Three shapes, nothing else

| Shape | Asks | Answer | Example |
| --- | --- | --- | --- |
| **Yes/No** | "Is this statement true?" | `true`/`false` (+ p if measured) | "Does this diff touch auth?" |
| **Pick one** | "Which of these N?" | one declared option | triage: `needs-info \| ready-for-agent \| ready-for-human \| wontfix` |
| **Level** | "Where on this rubric?" | one of 2–10 levels, **each with a written description** | severity: `1 cosmetic … 5 data loss / auth bypass` |

Rules:

- **The answer space is declared before the question is asked.** An answer
  outside it is a *failed* decision (re-ask or escalate), never something to
  interpret. "Mostly yes", "partially", "it depends" are out of space.
- **A level without a written anchor is not a rubric.** "High/medium/low"
  with no definitions gets a different meaning from each judge.
- **`unknown` is a legal option only when you declared it**, with what
  happens next. Never let it appear as a silent default.

## 3. Atomic questions; code composes

Ask one thing per question. Never ask "is this PR ready?". Ask *tests cover the
changed path? auth touched? scope matches ticket? checks green on this SHA?*,
then compute readiness from the answers with plain logic you can show. The
composition is deterministic, so it can be tested and argued with. A holistic
verdict can do neither.

## 4. Judge each question in isolation, against the same state

Each question sees the same state, never another question's answer or the
running conversation. That prevents anchoring (the second answer bending
toward the first) and context rot (a long thread degrading every later
judgment). In practice:

- Put the state in a fixed packet (diff, ticket text, evidence paths) and give
  each question the packet, not the thread.
- For independent verification, a separate judge per question, like blind
  finders. Never one judge answering a list in sequence.

## 5. Confidence gates the action. Confidence must be measured.

| Confidence | Action |
| --- | --- |
| High | act automatically |
| Medium | act only after a verifying check |
| Low, or out-of-space | escalate: stronger model, counterpart, or the user |

**Where confidence may come from: agreement across isolated judgments, a
measurable check, or a recorded outcome history. Never from a model's
self-report.** A model writing "confidence: high" is producing text, not a
measurement. Verbalized confidence is poorly calibrated, and a gate fed by it
is a control that never fires.

- **Agreement:** ask the same question to N isolated judges (different
  model or fresh context). Confidence = share that agree. Split → medium or low.
- **Check:** a target-state read that settles it (file contents, test on
  the changed path, remote SHA, HTTP status). A check that settles the
  question beats any number of judges.
- **Outcome history:** the decision ledger (below), which records past
  decisions at this point and whether each held up. This is the only honest
  way to tune thresholds. Until a row has enough resolved decisions,
  thresholds are human choices and must be labelled that way.

Humans set the thresholds and the acceptable risk. The agent never lowers a
threshold to get a decision through.

## 6. Typed is not correct

A well-formed answer can be confidently wrong. Type-safety removes junk output;
it does not remove wrong judgments. Calibration holds across a group of
decisions, never for any single one. High confidence on an irreversible,
security, data-loss or release decision still gets the check those rules
require.

## 7. Decision spec (write this before building a gate)

```
decision:     <name>
question:     <one atomic question>
shape:        yes/no | pick-one | level
answer space: <exact options; level anchors written out; unknown? → next step>
state:        <the packet each judge sees>
confidence:   agreement(N=…) | check(<command/target>) | outcome-history(<where>)
tiers:        high → <act>; medium → <verify how>; low/out-of-space → <escalate to>
thresholds:   <values> (human-set | tuned from outcome history on <date>)
```

## 8. Delegate return contract

When a delegate's job is a decision, it returns

```
{question, answer (from the declared space), evidence, confidence_source}
```

`confidence_source` is `agreement`, `check` or `history`, plus the
measurement. An answer outside the declared space, or a confidence that cites
only the delegate's own opinion, is a failed delegate. Re-ask or escalate;
don't interpret. This extends "a delegate returns measurements, not a
verdict": the answer may be a verdict only when it arrives with its
measurement.

## 9. Record it: the decision ledger

A gated decision nobody records can never be checked. Record it when you make
it, and resolve it when the truth arrives, which is often in a later session
or by a different agent. The ledger is append-only JSON lines at
`~/.local/state/agent-decisions/ledger.jsonl`, per machine.

```sh
L=~/.agents/skills/typed-decisions/scripts/decision-ledger.py
python3 $L record --point test-verdict --answer PASS --space "PASS|FAIL|BLOCKED|NOT RUN" \
  --source check --tier high --measurement "persona completed signup, read at target" \
  --ref "repo@<sha> signup"                        # prints the decision id
python3 $L resolve --ref "repo@<sha> signup" --point test-verdict \
  --outcome overturned --evidence "signup broken for the same persona on <sha>"
python3 $L report                                  # overturn rate per point, tier, answer
```

- **Always put a `--ref` a later agent can find**, such as the PR number,
  SHA, ticket or topic. Resolving goes by ref, since nobody remembers ids.
- **Resolve when you learn the truth, even about someone else's decision.**
  A finding later refuted, a PASS that later broke, a triage that bounced
  back, a scope verdict the user rejected: each is an `overturned`. A decision
  the next step relied on without trouble is `held`.
- **It refuses what the contract forbids** (exit 2): an answer outside the
  declared space, `--source none` with tier high/medium (a self-report), a
  measured source with no measurement, text that looks like a secret. Fix the
  decision; don't route around the ledger.
- **Hermes verdicts are imported automatically.** `import-hermes` reads the
  fleet plugin's stored verdicts (read-only) each day. An `accept` with no
  revise/reject on the same topic within 7 days resolves `held` (a labelled
  proxy). An `accept` followed by an objection is only **flagged**. Stored
  verdicts can't tell a real overturn from new work under a reused topic, so
  `report` lists the flags. Resolve one when you know which it was.
- The daily agent-hooks run imports, then fails `check` if the ledger is
  corrupt or nothing has been recorded for 14 days.

| Decision point | `--point` | Answer space |
| --- | --- | --- |
| Test verdict per goal | `test-verdict` | `PASS\|FAIL\|BLOCKED\|NOT RUN` |
| Review finding | `review-finding` | `confirmed\|refuted` |
| PR review verdict | `pr-verdict` | `APPROVE\|REQUEST_CHANGES\|COMMENT` |
| Security candidate | `security-finding` | `confirmed\|not-confirmed` |
| Scope verdict | `scope-verdict` | `aligned\|revise\|clarification` |
| Lane / model route | `route` | the declared lanes |
| Done / stop | `done` | `done\|not-done\|blocked` |
| Triage | `triage` | `needs-info\|ready-for-agent\|ready-for-human\|wontfix` |
| Hermes review (imported) | `hermes-review` | `accept\|revise\|reject` |

## Where this already applies

These decision points run on this contract. When you are at one, use its
declared space:

- **Test verdict** (`meaningful-tests`): pick-one `PASS | FAIL | BLOCKED | NOT RUN`
  per goal. PASS needs a check (the persona completed the goal).
- **Triage** (`issue-triage-state-machine`): pick-one; `ready-for-agent` needs
  agreement or evidence, otherwise `needs-info`.
- **Review findings** (`high-signal-pr-review`, `adversarial-security-sweep`,
  `reviewing-with-an-agent`): severity is a level with written anchors. The
  refute pass is one isolated yes/no per finding: "does it reproduce on the
  changed path?"
- **Scope** (`scope-advisor`): per requirement, yes/no `covered?` and yes/no
  `added-unrequested?`. The verdict `aligned | revise | clarification` is
  *computed* from those answers.
- **Routing** (`bb fleet route`, harness routing, `plan-arbiter`): lane is
  pick-one. Low confidence escalates to the architecture lane; it never falls
  to a silent default.
- **Counterpart trigger** (directive challenge): each risk trigger is a yes/no
  (touches auth? irreversible? unexplained failure? …). "Run a counterpart"
  is their OR, not a fresh judgment.
- **Stop / done** (`finish-the-job`): each stop reason is a yes/no with a
  check behind it. "Blocked" is legal only with the named blocker.
- **Hooks and guards**: allow/block is yes/no; out-of-space or error →
  block and report. Never allow by default.

## Not this

- Not for generation (code, docs, prose), which stays open-ended.
- No external decision-model dependency. Using a hosted System-One model in
  hooks is a separate, owner-approved decision.
- No self-reported confidence as a gate, anywhere.
