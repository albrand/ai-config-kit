# Token-Efficient Orchestration

Reconciles the High-Leverage Strategic Orchestrator mandate with the existing
non-negotiables in `GLOBAL_AGENTS.md`, `QUALITY_GATES.md`, and `TOKEN_ECONOMY.md`.

`TOKEN_ECONOMY.md` answers *how much* to spend. This file answers *what may be
cheapened without lowering the outcome bar*, and names the three places where a
naive cost-minimising policy silently buys wrong answers.

Read with `AGENT_ORCHESTRATION.md` (delegate contracts) and
`ADAPTIVE_MODEL_ORCHESTRATION.md` (effort routing). Where this file and a
cost-minimising instruction disagree, this file wins, because every rule below
exists to stop a measured failure rather than a hypothetical one.

## What The Reference Frameworks Actually Do

The mandate cites four projects. Their real mechanisms are more specific than
the shorthand, and the details change the policy.

**LangGraph — deltas for writes, full checkpoint for durability.** Nodes return
*partial* state updates and reducers merge them deterministically
(`Annotated[list, operator.add]`, `add_messages`), which also makes parallel
branches safe without coordination. But after each node the *full* state is
serialised to a pluggable checkpointer, and on resume the graph reloads that
checkpoint. Delta-passing is a write discipline, **not** a licence to discard
history — the durable record is what makes recovery possible at all.

**OpenHands — condensation is anchored and structured.** Its `Condenser`
operates over the event stream. `LLMSummarizingCondenser` triggers at
`max_size` (default 120 events), preserves the first `keep_first` events
(default 4) verbatim plus a recent tail, summarises the middle, and lands around
60 events. The summary is not free-form: it encodes goals, progress made, what
remains, and for software work the critical files and failing tests.
`PipelineCondenser` chains strategies. The lesson is `keep_first`: **the
original mandate is never summarised away.**

**Goose — tiered compaction and an explicit lead/worker split.** Auto-compaction
fires proactively at ~80% of the token limit, with context strategies as a
*backup* if the limit is still exceeded; `/summarize` triggers it early.
Separately, a lead/worker configuration runs an expensive model for planning and
a cheaper one for execution. Two tiers, and compaction is proactive rather than
a crash handler.

**Open Interpreter — stateful execution, results fed back.** A chain-of-thought
loop: model emits code, code runs, results return to the model. Variables,
imports, and results survive across messages. Execution state persisting is the
point; a "minimal payload" that discards it forces re-derivation.

## Protocol 1: Radical Delegation, Evidence Returned

Delegate boilerplate, file-scoped edits, and syntax repair. Keep architecture,
security, data-loss, ambiguity, and final verification on the strongest path.
This matches Goose's lead/worker split and is unchanged from the mandate.

**Amendment — a delegate returns evidence, not a verdict.** `{status: pass}` is
not a State Delta; it is an assertion. Require:

```
{ claim, measurement, before, after, command, exitCode, artifact }
```

Rationale: a bare pass/fail was wrong repeatedly in one measured session. A
worker reporting which model it ran is the one field that cannot settle "did the
cheap tier cause this?" — so the orchestrator stamps the assignment at dispatch
and never trusts self-report for it.

**Amendment — a decision comes back typed.** When the delegated job is a
decision (classify, triage, pass/fail, does this reproduce), the brief declares
the answer space and the delegate returns
`{ question, answer, evidence, confidence_source }`. The answer must come from
that space. `confidence_source` is `agreement`, `check` or `history`, plus the
measurement. An out-of-space answer, or a confidence that cites only the
delegate's own opinion, is a failed delegate. See the `typed-decisions`
skill.

**Amendment — parsing logs is diagnosis, not clerical work.** "Do not parse raw
terminal logs" applies to routine output. When diagnosing, the log *is* the
evidence: stage timings, row counts, and byte counts identified a real
bottleneck that a summarised "it failed" would have hidden. Delegate the
parsing; require the numbers back.

## Protocol 2: Effort Is A Resource Choice, Not A Correctness Profile

Reconciles the mandate's "set reasoning effort to minimum" with the standing
rule in `GLOBAL_AGENTS.md`. Both apply; the standing rule is the constraint.

Minimum effort is permitted for work that is **reversible and mechanically
verifiable**: formatting, boilerplate, syntax repair, deterministic transforms.

Minimum effort is **prohibited** for:

- irreversible or hard-to-undo actions (destructive edits, releases, migrations,
  anything leaving the machine);
- security, auth, secrets, data-loss surfaces;
- diagnosis of an unexplained failure;
- any conclusion that a plausible-looking result is correct.

Every effort level inherits identical outcome criteria, evidence requirements,
and stop conditions. If a lane cannot satisfy the gate, do not route there.

Measured basis: in one session, the cheap reading was wrong in six distinct
cases — a self-update that reported success while changing nothing, a
compaction that "succeeded" while the measured bytes were byte-identical, a
proposed bulk delete that measurement showed would recover ~3% of the cost for
real risk, a config writer misattributed to the wrong process, a
re-authentication that never touched its target file, and a retry that caused
the outage it was written to absorb. Each was caught by measuring, not by
reasoning harder — but none would have been measured under "do not
over-analyse deterministic logic".

## Protocol 3: Context Hygiene With A Durable Floor

Keep the mandate's direction: pass deltas, prune redundancy, compress
aggressively near context limits. Adopt Goose's proactive threshold rather than
waiting for an overflow error.

**Amendment — never prune your own mutations.** Maintain an append-only change
ledger, exempt from pruning, recording every state-changing action: what
changed, where, when, and how to reverse it. This is the LangGraph checkpoint,
not the LangGraph delta.

Rationale: a self-inflicted regression is only detectable by correlating a
present symptom with a change made much earlier. Under an aggressive prune
policy that history is classified as a stale trial-and-error log and deleted —
and the agent then diagnoses its own damage as an external fault. In the
measured case, the loop was found *only* because the earlier change was still
known.

**Amendment — adopt `keep_first`.** Never summarise away the original request,
accepted scope revisions, or standing constraints. Condense the middle. Keep the
head verbatim and a recent tail, exactly as `LLMSummarizingCondenser` does.

**Amendment — structure the summary.** Follow OpenHands: goals, progress, what
remains, critical files, failing checks, open questions. Not free prose.

## Protocol 4: Deterministic Guardrails That Assert On State

Keep the mandate's circuit breaker: after N failed validations (default 3),
intercept; never let a delegate loop. Keep "never use an LLM to judge whether a
test passed."

**Amendment — assert on target state, not on the process's self-report.** An
exit code is a claim by the process about itself. Measured counterexamples, all
exit 0: a CLI update that performed no update; an authentication flow that
printed success and left the credential file untouched; a scheduled job that
"succeeded" having done nothing because the item was already claimed.

The deterministic check must read the thing you care about — installed version,
file mtime, row count, bytes scanned, ledger contents, HTTP status — and
compare it against an expected value. Exit code is corroborating, never
sufficient.

**Amendment — retries and probes need a cost model.** A retry that re-queries a
rate-limited dependency generates the failure it is absorbing. Any automatic
retry against a shared or metered resource carries:

- a bounded attempt count (small; 2 is usually right);
- a cooldown after sustained failure, dropping to a single attempt;
- a short-TTL cache of *successful* reads only — never cache a failure, or one
  bad read is held for the whole TTL;
- a test-mode switch, because a cache that answers before the stubbed call is
  reached will silently invalidate the test suite that guards it.

Measured basis: a 3-attempt retry plus routine polling drove a metered
telemetry endpoint from intermittent failure to total failure; ~3.5 minutes of
no polling restored it. Adding a 45s success-cache reduced repeated invocations
to zero upstream calls.

## Output Contract

```
STATUS:      current milestone state
BLUEPRINT:   dense structural commands for workers (file mappings, schema, contracts)
DELEGATION:  isolated execution blocks routed to the cheapest capable worker
EVIDENCE:    measurements backing STATUS — command, expected, observed
CORRECTIONS: prior claims in this task now known to be wrong, and what replaced them
PRUNE:       context safe to drop next turn (never the change ledger, never the head)
```

`EVIDENCE` and `CORRECTIONS` are required. Without `EVIDENCE`, `STATUS` is an
assertion. Without `CORRECTIONS`, a superseded wrong conclusion stays live in
the record and is acted on later — the most expensive failure mode here, and
strictly cheaper to state than to let a worker rediscover.

`PRUNE` names only redundant intermediate content. It may never list the change
ledger, the original request, accepted scope revisions, or standing constraints.

## Anti-Patterns

- Reporting success from an exit code without reading the resulting state.
- Returning `{status: pass}` as a State Delta.
- Pruning the record of your own changes.
- Summarising the original mandate into a paraphrase.
- Retrying into a metered dependency without cooldown or cache.
- Caching a failed read.
- Adding a short-circuit ahead of a stubbed call without a test-mode switch.
- Treating minimum effort as permission to lower the evidence bar.

## Sources

- OpenHands condenser: <https://docs.openhands.dev/sdk/arch/condenser>
- OpenHands context condensation:
  <https://www.openhands.dev/blog/openhands-context-condensensation-for-more-efficient-ai-agents>
- Goose smart context management:
  <https://block.github.io/goose/docs/guides/smart-context-management/>
- LangGraph state, reducers, and checkpointing:
  <https://langchain-ai.github.io/langgraph/concepts/low_level/>
- Open Interpreter architecture: <https://docs.openinterpreter.com/>
