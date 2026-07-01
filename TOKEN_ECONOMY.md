# Token Economy

Concrete recipes for reducing token spend across master, delegated agent, and
cross-agent work. Complement to `HARNESS_STRATEGY.md`: strategy says *what* to
route, this file says *what saves measurable cost when you route*.

Numbers below come from user reports, not controlled studies. Treat them as
order-of-magnitude evidence, not guarantees.

## Empirical Baseline

- ~73% of a typical agent API call is fixed overhead - system prompts,
  persistent memory, gateway processing, tool schemas. That floor is paid
  every turn regardless of useful work. The largest leverage is upstream
  (routing, memory hygiene), not shaving words off a prompt.
- User-reported cost reductions of ~90% on real workloads come from
  *provider and model selection*, not prompt compression. A bad default
  routing setup can run 10x a good one with identical task quality.
- Prompt compression on real coding tasks saves ~14-21% (well below the
  ~60-75% headline numbers from synthetic benchmarks).
- Output compression on chatty CLI tools saves 60-90% on a 30-minute
  session because it strips noise the model never needed to see.

## Model Tier Mapping

Map work to the smallest tier that can complete it with high confidence and
validation. Examples are illustrative; the actual map depends on the active
harness.

| Tier | When | Claude Code examples | Mixed-provider examples |
|------|------|---------------------|-------------------------|
| Small / local | Classification, file discovery, formatting, JSON shaping, log summary, naming, deterministic refactors | `Agent(subagent_type: "Explore")`, `Agent(model: "haiku")` | Local OpenAI-compatible sidecar, Gemini Flash Lite, Minimax M2.7 |
| Medium | Localized code, component implementation, test generation, doc drafting, API integration, mapping requirements to files | `Agent(model: "sonnet")`, `Agent(subagent_type: "general-purpose")`, `Agent(subagent_type: "Plan")` | Claude Sonnet, GPT-5.4 Mini |
| Large / frontier | Architecture, ambiguous debugging, security-sensitive work, data-loss risk, multi-system planning, final pre-merge review, prompt or harness redesign | Master thread (Opus 4.7), `advisor` | Claude Opus, GPT-5.4, Hermes flagship |

Anti-pattern: routing all work to the strongest tier "to be safe". Frontier
should own judgment; mechanical work goes a tier or two down.

## Local Sidecar Routing

When a local OpenAI-compatible sidecar is configured, use it before hosted
models for bounded no-tool cognition:

- Classification, extraction, naming, JSON shaping, prompt compression, and
  noisy-output summaries.
- First-pass critique when the source-of-truth evidence is already compact.
- Rewriting verbose context into a smaller brief for Spark or another worker.

Operational constraints:

- Keep prompts small and explicit; do not paste whole framework files or raw
  transcript history.
- Use tool-free system instructions, hard output caps, and a short timeout.
- Do not send secrets, credentials, or broad private context.
- Treat output as advisory. The master verifies before acting.
- If the sidecar is unavailable, times out, or needs tools, route to GPT 5.3
  Spark or keep the work in the master thread.

When the user or repo declares local-sidecar delegation required, make at least
two independent no-tool delegations before implementation or final judgment:
one planner/decomposer pass and one critic/verifier pass. For harness, prompt,
routing, or process changes, add a third operator pass that turns the output
into a concrete operating contract. Reconcile the outputs instead of copying
them verbatim.

For directive, planning, architecture, or challenge/advisor briefs, include the
authorization sentence or equivalent: "Authorization: the user explicitly
authorizes sidecar/counterpart model use for directive and architecture
challenges for this run." Keep it out of trivial briefs to avoid token tax and
authorization fatigue.

When scanning sibling projects under `/Users/alexandrebrandizzi/projects` for
candidate implementation patterns, use a metadata-first budget: list names,
stack markers, and likely pattern files before opening code. Do not send
secrets or broad private context to sidecars, and adopt only patterns that fit
the current repo's stack and constraints.

## GPT 5.3 Spark Routing

When Codex exposes model choice, treat GPT 5.3 Spark as the first-choice
bounded worker or explorer tier for quick and standard subtasks that are
reviewable and cheap to validate. When a Codex model slug is required, use
`gpt-5.3-codex-spark`.

Use Spark for file discovery, scoped codebase questions, log or test-output
summaries, PR or check metadata extraction, formatting, JSON shaping,
mechanical refactors, localized test updates, small docs edits, and focused
worker patches with disjoint ownership.

Do not use Spark for architecture, security, auth, data-loss decisions,
production release gates, ambiguous debugging, broad cross-module refactors,
dependency strategy, final pre-merge verdicts, or any task where failure would
be expensive to detect. Keep those decisions in the master thread or strongest
available reasoning path.

Before escalating delegated quick or standard work to a stronger Codex tier,
run a Spark-fit check and record the exception reason if Spark is not used.
Spark delegates should stop and escalate with a concise blocker when
requirements conflict, scope expands, validation fails twice, security or data
concerns appear, or broad context is needed.

## Swarm Authorization Phrase

If the live user prompt includes the exact phrase `subagents swarm allowed`,
treat it as explicit authorization and request wording for sub-agents, parallel
delegation, model routing, and cross-agent counterpart routing for the current
prompt or thread.

The phrase is a routing enablement signal, not a spend mandate. Use the
smallest capable model or agent, cap delegated output, preserve exact
source-of-truth snippets, and keep local execution when delegation overhead
costs more than it saves.

## Subagent Prompt Discipline

When delegating to a sub-agent or smaller model:

- Keep the **structure** of the delegation brief: objective, scope, do-not-touch,
  context, allowed outputs, success criteria, validation, escalation. The
  agent has no shared context with the master; structure is its scaffolding.
- Compress the **content**: drop articles, glue words, hedges, and motivational
  filler. "Read X. Report Y. Do not Z." is enough. The agent does not need
  encouragement.
- Quote source-of-truth **verbatim only where exactness matters**: file paths,
  type names, function signatures, schema field names, error strings. Never
  paraphrase those.
- Do not paste framework files into a sub-agent prompt. Reference by path; the
  agent can `Read` them if needed.
- Cap output explicitly: "under N words", "as a punch list", "report only
  failed checks". Long sub-agent reports inflate the master thread's context
  for no decision benefit.

## Progressive Disclosure And Mechanical Reduction

Adopt the Hermes-style pattern: disclose context in layers, and make tools do
mechanical reduction before the model reasons.

- Start from indexes, filenames, metadata, status summaries, and filtered API
  fields.
- Load full skill bodies, reference docs, PR bodies, issue descriptions, logs,
  or framework files only when the next decision needs them.
- Use `rg`, `--json`, `--jq`, counts, sorted lists, and focused status filters
  to collapse raw evidence before adding it to the reasoning context.
- Preserve exact source-of-truth strings only where exactness matters: paths,
  identifiers, schema names, type names, function signatures, error strings,
  diffs, failures, and security findings.
- Prefer "script output as context": scripts fetch, diff, count, or classify;
  the agent reasons over the compact result.

## Trajectory-Style Compression

For long-running workflows, compress the middle and preserve the edges:

- Preserve: original objective, active constraints, governing instructions,
  recent evidence, current plan, unresolved risks, and validation state.
- Compress: old successful command output, repeated status dumps, superseded
  plans, already-integrated sub-agent reports, and exploration that no longer
  affects the decision.
- Never compress away failing test output, build errors, security findings,
  schema details, exact error strings, or conflicting requirements.

## Output Filtering

Chatty tool output spends tokens on noise the agent rarely needs:

| Tool / command | Compress to | Skip when |
|----------------|------------|-----------|
| `git status` / `git log` | first line + counts | doing a review pass |
| `pnpm install`, `npm install` | "ok, N packages added" or non-zero exit | install failed |
| Container/build logs | grep for errors first | debugging build failure |
| Test runners on pass | "N passed in Ts" | a test failed |
| `ls`, `find` | counts + first dozen entries | the listing *is* the answer |

Patterns that should **not** be compressed at the tool boundary:

- `git diff` - full diff is the review surface.
- Test failure output - full stack and assertion is required to debug.
- Build errors - full error context maps to the fix.
- Anything the agent will quote verbatim back to the user.

If the harness supports a `PreToolUse` hook, an output proxy like
`rtk` (`https://github.com/rtk-ai/rtk`) installs at the tool boundary and
silently compresses chatty commands. Adopt only when:

- The harness supports the hook layer (Claude Code, Codex, Cursor).
- The proxy supports each tool the agent uses; otherwise it falls through.
- The team has agreed on which commands are "chatty" (review the proxy's
  command list before installing).
- The proxy can be disabled per-command when full output matters (diff,
  failures).

The proxy is an optimization, not a substitute for the agent reading carefully.
On any failure path, treat compressed output as suspect and re-run the raw
command.

## Cross-Agent Cost Control

When another AI tool can work alongside the coordinator, use it deliberately.
The goal is not to spend twice; it is to keep the coordinator's high-value
context focused on judgment while another tool handles bounded work.

- Use a counterpart for peer critique, exploration, test design, validation,
  or summarization when that output changes the coordinator's decision.
- Require a communication plan from `CROSS_AGENT_COORDINATION.md` before
  substantial joint work: role split, context package, output cap, budget, stop
  conditions, and fallback.
- Keep the counterpart prompt narrower than the coordinator's context. Send
  exact paths, commands, and constraints, not the full thread.
- Prefer cheap or mid-tier counterpart models for mechanical work. Reserve
  high-tier counterpart use for independent architecture or risk critique.
- Set a hard budget when the tool supports it, such as a dollar cap, turn cap,
  elapsed-time cap, or output word cap.
- If the coordinator must invoke the counterpart outside a sandbox to reach
  local auth, keep that command narrowly scoped and use the smallest practical
  budget cap.
- Treat Claude CLI as a first-class counterpart when available: prefer bounded
  `claude -p` calls with explicit escalation for outside-sandbox auth,
  `--max-budget-usd`, output caps, stop conditions, and sanitized context by
  default.
- If an approval reviewer blocks external-AI handoff because the brief contains
  private board, release, customer, secret, or environment context, do not route
  around the block. Fall back to local verification or produce a paste-ready
  prompt for an approved environment.
- Treat unauthenticated, rate-limited, or unavailable counterpart tools as a
  normal capability gap. Continue single-agent execution without weakening
  validation.

## Memory Discipline

Persistent memory loads every session. Bloat costs every conversation, not
just one.

- Memory holds pointers and unobvious facts. Framework content stays in the
  framework; reference it from memory, do not copy it.
- Compress completed work into one-paragraph "summary cards" (the
  Task-Centric Memory pattern). Discard raw transcripts.
- Cap memory-index files (~200 lines). They fit cheaply in every preamble
  and stay scannable.
- Set decay conditions on time-bound memories ("delete when branch X
  merges", "stale after release Y"). Stale memory is worse than no memory.

## When To Skip All Of This

- Trivial single-turn work: do not route, do not coordinate another AI, do not
  delegate, do not compress. Apparatus overhead exceeds the savings.
- Security, data, auth, release, or architecture work: full reasoning,
  full validation, full evidence trail. Cost is not the constraint here;
  truth is.
- First-pass exploration: full output is acceptable while learning the
  surface. Tighten on the second pass.

## Sources

- Hermes Agent user stories - multi-tier routing, multi-agent pipelines,
  measured fixed overhead (Nous Research, May 2026).
- "Caveman" prompt compression - semantic compression by stripping
  predictable grammar (`https://github.com/wilpel/caveman-compression`,
  2026); benchmarked at 14-21% real-task savings vs. ~60-75% headline
  claims.
- RTK (Rust Token Killer) - `PreToolUse` proxy for chatty CLI output
  (`https://github.com/rtk-ai/rtk`, 2026); reported 60-90% session savings.
- Microsoft LLMLingua - small-model prompt compression at 20x ratio with
  ~1.5-point reasoning-task degradation.
