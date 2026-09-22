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
verified: 2026-09-22
---

# Typed decisions

Adapted from TypeSafe AI's "System One" model, Jev. Jev never generates text:
it takes *state + typed questions* and returns an answer from a fixed answer
space, with a probability, in one pass. We take the method, and where the
judgment is semantic we run it on the model too (section 10).

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
- **System One:** a calibrated decision model (Jev) answering the typed
  question in isolation, recorded as `system-one`. It is a trained probability,
  not a verbalized one, but its calibration in your domain is proven only by
  outcome history. Section 10 sets its limits.

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

`confidence_source` is `agreement`, `check`, `history` or `system-one`, plus
the measurement. An answer outside the declared space, or a confidence that cites
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

## 10. Run it on System One (Jev)

The owner approved using TypeSafe's hosted System One model, Jev, for agent
decisions. It does natively what sections 2–5 ask for: a typed answer from a
declared space, isolated per question, with a *trained, calibrated* probability
instead of a sentence about confidence. It is fast and cheap enough to ask
often. Use it.

```sh
J=~/.agents/skills/typed-decisions/scripts/jev.py      # same path in every skill home
python3 $J --state-file packet.json \
  --yn    auth   "Does \`diff\` change authentication or authorization?" \
  --pick  triage "Where does \`issue\` go next?" "needs-info=no repro or expected result|ready-for-agent|ready-for-human|wontfix" \
  --level sev    "How severe is the risk in \`diff\`?" "cosmetic|minor, workaround exists|broken feature|data loss or auth bypass" \
  --record --point "triage=triage" --ref "repo#123"
```

`--yn` → probability of yes; `--pick` → one option plus the distribution;
`--level` → one written anchor plus the distribution. `--spec file.json` takes
a raw TypeSafe questions map (structured instructions, criteria objects).
The endpoint comes from `TYPESAFE_BASE_URL` (on this setup:
`{{SYSTEM_ONE_BASE_URL}}`, which injects the key; `TYPESAFE_API_KEY` can be any
placeholder there).

**Use Jev when all of these hold:** section 1 says it is a decision; the
judgment is about *meaning* (reading a diff, ticket, message, log, finding),
not something a command can settle; the needed state fits in one packet; and
an expert would answer it in seconds. **Don't** use it for System-2 work
(multi-step reasoning, arithmetic, running code, tracing call graphs), for deep
specialist domains without validation, or for generation.

**Where it pays on this setup:**

| Decision point | Jev question |
| --- | --- |
| `scope-advisor` | per requirement: `--yn covered`, `--yn added_unrequested`; the verdict is still computed |
| review / security refute pass | per candidate: `--yn reproduces "Does \`finding\` hold on the changed lines in \`diff\`?"`, as one more blind judge |
| severity | `--level` with the skill's written anchors |
| triage | `--pick` over the declared triage states |
| route / lane | `--pick` over the declared lanes, each with a one-line description |
| counterpart trigger | one `--yn` per risk trigger in one call; "run a counterpart" is their OR |
| done / stop | `--yn` per semantic stop reason (e.g. "does this report name a blocker?"); PASS still needs a check |

**How to ask well:** put the facts in `state` as named JSON fields and refer to
them in backticks. Batch every independent question about the same packet into
one call: they run in parallel, can't see each other, and cost one round trip.
Ask a second call only when an earlier answer decides what to fetch next.
Write criteria that separate the options, and include a no-match option when
none may fit. Read the live guide before designing a new gate:
`https://docs.typesafe.ai/llms.txt`.

**Confidence and tiers.** Record Jev answers with `--source system-one`
(`--record` does it). `jev.py` assigns the tier from human-set thresholds
(yes/no: p ≥ 0.90 or ≤ 0.10 high, ≥ 0.75 or ≤ 0.25 medium; pick/level:
confidence ≥ 0.85 high, ≥ 0.60 medium). Then:

- **Reversible and low-stakes:** a high tier may act.
- **Irreversible, security, data, auth, release:** Jev alone caps at medium.
  It still needs the check those rules require.
- **Agreement:** your own isolated judgment plus Jev on the same packet is
  `agreement(N=2)`. Agree → record `--source agreement`; disagree → low →
  escalate. That makes Jev the cheapest independent second judge you have.
- **Tune from history, not taste:** `decision-ledger.py report --source
  system-one`. Once a point has ~20 resolved decisions, move its thresholds
  to what the overturn rate supports, and say so.

**Privacy:** the state leaves this machine. Send the minimal packet: a diff
hunk, ticket text, a redacted log. Never send credentials, personal data,
patient or client records, or production data. `jev.py` refuses state that
looks like a secret; personal data is on you.

**Failure** (exit 3, service down or quota): don't invent an answer. Judge it
yourself, record `--source none --tier low`, and escalate if it gates
anything.

**Velocity.** Every `--record` call also stores the call's `latency_ms`,
`tokens`, `batch` and the asking agent. `decision-ledger.py velocity` reports
per-decision cost by source, system-one decisions per day, the latest
benchmark, and the model time and tokens saved so far. `jev-bench.py` refreshes
the benchmark: labelled decision cases answered by Jev and by `claude -p`
models, each at its cheapest (one call per state, no tools, API time only),
scored for accuracy as well as speed. Quote velocity from that report, never
from memory, and re-run the bench when a model changes. A faster method that
loses accuracy is not an improvement.

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
- Not a blocking hook. A System One call is a network round trip that can fail
  or hit a quota; a PreToolUse gate that depends on it fails closed on every
  tool call. Use it in skill steps and advisory reports, never as the only
  thing standing between an agent and a tool.
- Not a substitute for a check. When a command can settle the question, run
  the command.
- No self-reported confidence as a gate, anywhere.
