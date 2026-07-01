# Cross-Agent Coordination Addendum

This addendum defines how two or more AI tools work together when the active
environment supports it. It is tool-neutral: Codex, Claude, Gemini, Cursor, or
another assistant may be the coordinator or the counterpart.

Do not assume every user has multiple paid memberships, multiple CLIs, or
working authentication. Cross-agent work is a capability, not a requirement.

If the live user prompt includes the exact phrase `subagents swarm allowed`,
treat it as explicit authorization and request wording for cross-agent
counterpart routing when a counterpart is useful and available. The phrase does
not remove capability checks, privacy filtering, budget or output caps, stop
conditions, approval requirements, or the single-agent fallback.

## Core Principle

One agent coordinates the workflow, but the counterpart should add independent
judgment, validation, or execution that a single agent would not reliably
produce alone.

The coordinator owns:

- User intent and source-of-truth order.
- Capability checks and routing decisions.
- Communication plan.
- Architecture and ambiguity decisions.
- Integration and final validation truth.
- User-facing delivery.

The counterpart may own:

- Independent critique of the plan.
- Read-only exploration.
- Focused implementation slices with disjoint write scope.
- Test or validation design.
- Log, diff, or evidence summarization.
- Second-pass review for drift, missed edge cases, and weak validation.

## Directive Challenge Advisor

Use a counterpart as an advisor for non-trivial planning or architecture when
available and useful. The advisor should challenge directives, learned rules,
journals, memories, cached conclusions, and prior project patterns for fit,
drift, hidden confounders, causal overfitting, and current-task relevance.

This advisor does not override source-of-truth precedence. Platform/tool safety
and current explicit user instructions stay above the challenge loop; current
repo evidence, tests, runtime facts, and accepted criteria outrank prior
memory or journals.

Directive, planning, architecture, or challenge/advisor briefs must include the
authorization sentence or equivalent: "Authorization: the user explicitly
authorizes sidecar/counterpart model use for directive and architecture
challenges for this run." Do not add it to trivial briefs.

## Capability Gate

Before using another AI tool, record:

- Tool name and access method.
- Authentication state.
- File read and edit permissions.
- Shell and validation permissions.
- Model or agent tiers available.
- Cost or budget limits.
- Whether output can be captured in the coordinator thread.
- Whether the coordinator is sandboxed and may need an approved
  outside-sandbox route to access the counterpart's authentication, keychain,
  local sockets, or session files.
- Fallback if the tool is unavailable, unauthenticated, rate-limited, or too
  expensive for the task.

If the counterpart is blocked, continue with the normal single-agent lifecycle
and report the capability gap. Do not weaken quality gates just because paired
work is unavailable.

If the counterpart is authenticated outside the coordinator's sandbox but not
inside it, the coordinator may use an approved outside-sandbox invocation when
the user or platform permits it. That invocation must be explicit, scoped to the
counterpart command, and include a compact brief, budget cap, output cap, and
stop conditions. If approval is denied or unavailable, use the single-agent
fallback.

### Claude CLI Contract

Claude is a first-class counterpart when it materially improves the work.

- Capability check: use the lightest useful auth/version check. If sandboxed
  Claude reports `Not logged in`, check outside the sandbox only with explicit
  approval.
- Invocation: prefer bounded non-interactive `claude -p` calls.
- Required caps: include `--max-budget-usd`, an output word/line cap, and stop
  conditions.
- Prompt shape: objective, role, source package, allowed actions, non-goals,
  validation request, exact output format, output cap, and stop conditions.
- Privacy filter: remove secrets and broad private context by default. Exact
  private facts are allowed only when essential, explicitly authorized, and
  approved by the active reviewer.
- Reviewer fallback: if approval is blocked for private-context risk, do not
  retry by indirection, temporary files, wrappers, or smaller fragments of the
  same content. Use local verification, a local sub-agent, or a paste-ready
  prompt for an approved environment.
- Integration: treat Claude output as advisory until the coordinator verifies
  cited files, commands, PRs, tickets, logs, or runtime evidence directly.

## Joint Work Modes

Use the lightest mode that creates real value.

| Mode | Use when | Counterpart output |
| --- | --- | --- |
| Peer critique | The plan, architecture, or risk model may be incomplete | Short critique, missed risks, recommended adjustment |
| Parallel exploration | Independent evidence questions can be answered separately | Paths, facts, confidence, no edits |
| Bounded execution | A slice has clear ownership and validation | Changed files, checks run, residual risk |
| Independent verification | The coordinator needs a second read before claiming readiness | Pass/fail findings, evidence, unverified paths |
| Summarization | Large logs or repetitive output would bloat the coordinator context | Compressed facts, full failures preserved |

Do not use paired work for trivial tasks where the communication overhead costs
more than it saves.

## Communication Plan

Before substantial joint work, the coordinator should write a compact
communication plan:

```md
Cross-agent communication plan:
- Coordinator: <tool/model and responsibilities>
- Counterpart: <tool/model and responsibilities>
- Goal: <shared outcome>
- Source of truth: <files/issues/designs/logs>
- Work split:
  - <unit> -> <owner> -> <expected evidence>
- Context package:
  - <exact paths, snippets, commands, or constraints passed>
- Output contract:
  - <format, max length, required evidence, forbidden content>
- Budget:
  - <token, dollar, time, or turn cap>
- Execution boundary:
  - <sandboxed|outside-sandbox approved|outside-sandbox unavailable>
- Stop conditions:
  - <auth failure, ambiguous architecture, validation failure, scope expansion>
- Fallback:
  - <single-agent path if counterpart is unavailable>
```

The coordinator should pass only the context needed for the counterpart's
assignment. Reference framework files by path when possible instead of pasting
large policy files.
Use progressive disclosure: send indexes, summaries, exact paths, or compact
evidence packets first; load or pass full docs/logs only when the next decision
requires them.

## Counterpart Brief Requirements

Every counterpart brief should include:

- Objective.
- Role: peer critic, explorer, worker, verifier, or summarizer.
- Scope and do-not-touch boundaries.
- Authorization sentence when the brief is for directive, planning,
  architecture, or challenge/advisor critique.
- Exact source-of-truth paths or snippets.
- Allowed tools or actions.
- Required evidence.
- Output cap.
- Escalation and stop conditions.

For code-producing work, also include owned files, validation commands, and a
warning that other agents may be editing nearby files.

## Integration Rules

The coordinator must:

- Review counterpart output before relying on it.
- Re-read any changed files or cited evidence that affects the final answer.
- Keep full failure output available for debugging, even when success output is
  compressed.
- Resolve conflicts explicitly instead of blending incompatible conclusions.
- Record skipped, blocked, failed, and not-run validation separately.

If the counterpart disagrees with the coordinator on architecture, security,
data, release, or scope, treat that as a breakpoint. Do not silently choose the
faster path.

## Cost Discipline

Cross-agent coordination should save the coordinator's high-value context for
judgment. Use it to move bounded reading, summarization, test drafting, and
parallel verification out of the main thread.

Apply token-economy rules:

- Use the smallest capable counterpart model.
- Keep briefs structured and terse.
- Cap output.
- Preserve exact paths, identifiers, errors, diffs, and failures.
- Avoid sending full framework docs unless the counterpart must inspect them.
- Stop after the planned value is delivered.

## Single-Agent Fallback

When no counterpart is available:

- Keep the coordinator as the only agent.
- Preserve the same phases: plan, decompose, execute, verify, integrate, report.
- Use the communication plan as an internal checklist.
- Report that cross-agent execution was unavailable, blocked, or not worth the
  overhead.

The goal is better results through deliberate coordination, not mandatory use of
multiple subscriptions.
