# Token Economy

Concrete recipes for reducing token spend across master and delegated agent
work. Complement to `HARNESS_STRATEGY.md`: strategy says *what* to route, this
file says *what saves measurable cost when you route*.

Numbers below come from user reports, not controlled studies. Treat them as
order-of-magnitude evidence, not guarantees.

## Empirical Baseline

- ~73% of a typical agent API call is fixed overhead — system prompts,
  persistent memory, gateway processing, tool schemas. That floor is paid
  every turn regardless of useful work. The largest leverage is upstream
  (routing, memory hygiene), not shaving words off a prompt.
- User-reported cost reductions of ~90% on real workloads come from
  *provider and model selection*, not prompt compression. A bad default
  routing setup can run 10× a good one with identical task quality.
- Prompt compression on real coding tasks saves ~14–21% (well below the
  ~60–75% headline numbers from synthetic benchmarks).
- Output compression on chatty CLI tools saves 60–90% on a 30-minute
  session because it strips noise the model never needed to see.

## Model Tier Mapping

Map work to the smallest tier that can complete it with high confidence and
validation. Examples are illustrative; the actual map depends on the active
harness.

| Tier | When | Claude Code examples | Mixed-provider examples |
|------|------|---------------------|-------------------------|
| Small / local | Classification, file discovery, formatting, JSON shaping, log summary, naming, deterministic refactors | `Agent(subagent_type: "Explore")`, `Agent(model: "haiku")` | Gemini Flash Lite, local Qwen3 4B, Minimax M2.7 |
| Medium | Localized code, component implementation, test generation, doc drafting, API integration, mapping requirements to files | `Agent(model: "sonnet")`, `Agent(subagent_type: "general-purpose")`, `Agent(subagent_type: "Plan")` | Claude Sonnet, GPT-5.4 Mini |
| Large / frontier | Architecture, ambiguous debugging, security-sensitive work, data-loss risk, multi-system planning, final pre-merge review, prompt or harness redesign | Master thread (Opus 4.7), `advisor` | Claude Opus, GPT-5.4, Hermes flagship |

Anti-pattern: routing all work to the strongest tier "to be safe". Frontier
should own judgment; mechanical work goes a tier or two down.

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

- `git diff` — full diff is the review surface.
- Test failure output — full stack and assertion is required to debug.
- Build errors — full error context maps to the fix.
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

- Trivial single-turn work: do not route, do not delegate, do not compress.
  Apparatus overhead exceeds the savings.
- Security, data, auth, release, or architecture work: full reasoning,
  full validation, full evidence trail. Cost is not the constraint here;
  truth is.
- First-pass exploration: full output is acceptable while learning the
  surface. Tighten on the second pass.

## Sources

- Hermes Agent user stories — multi-tier routing, multi-agent pipelines,
  measured fixed overhead (Nous Research, May 2026).
- "Caveman" prompt compression — semantic compression by stripping
  predictable grammar (`https://github.com/wilpel/caveman-compression`,
  2026); benchmarked at 14–21% real-task savings vs. ~60–75% headline
  claims.
- RTK (Rust Token Killer) — `PreToolUse` proxy for chatty CLI output
  (`https://github.com/rtk-ai/rtk`, 2026); reported 60–90% session savings.
- Microsoft LLMLingua — small-model prompt compression at 20× ratio with
  ~1.5-point reasoning-task degradation.
