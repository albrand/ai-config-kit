---
name: measuring-agent-spend
description: >
  Use when building or debugging token/cost accounting across agent providers,
  or when a spend dimension renders empty. Covers what each event source can and
  cannot tell you, why skill usage is nearly invisible, and how to bucket a
  usage chart so it is readable at every window.
verify: "test -n \"$HOME\""
verified: 2026-08-13
---

# Measuring agent spend

## Know what each source can answer

Three sources, and they do not overlap the way you would expect:

- **The orchestrator's event log** (bb: `thread log`) records `toolCall` items
  with a `tool` name and an `arguments` object, `commandExecution`, `reasoning`,
  `fileChange` and `contextCompaction`. It is the right source for tools, shell
  commands, threads, machines and projects.
- **Provider-native usage events** carry the actual numbers. Under bb that is
  `thread/tokenUsage/updated`, provider-neutral, with input / cached input /
  output / reasoning. **ACP providers emit none of it** — only
  `contextWindowUsage.usedTokens`, which is a context size, not consumption.
  Never add a proxy derived from it into a spend total; keep it in its own
  column and label the coverage debt.
- **The provider's own transcript** (Claude Code: `~/.claude/projects/<slug>/
  *.jsonl`) records things the orchestrator never sees.

That third one matters more than it looks.

## Skill usage is almost invisible, and here is exactly why

A "spend by skill" chart is an obvious thing to want and a hard thing to
populate. Skills reach an agent three different ways and only one leaves a trace
in the orchestrator:

1. **Invoked as a tool** — a `Skill` tool call whose payload names the skill.
   Observable, but rare: 1 invocation in 5129 transcript lines of a long
   session.
2. **Loaded by reading the file** — the agent Reads `.../<name>/SKILL.md`. That
   read is the only trace. Attribute it to the skill rather than to `tool:Read`,
   or it disappears among file access. Require a `skill`-ish ancestor directory:
   matching the last directory alone turns a stray `/Users/me/SKILL.md` into a
   skill named after the home directory.
3. **Injected into context by the harness** — the common case, and it leaves
   **no event at all**. Not a tool call, not a read, nothing.

So a skill dimension can be correct, well-tested, and still empty. Say that in
the empty state. "Nothing recorded" reads as a broken filter and gets reported
as a bug; the note should name the mechanism and say what would populate it.

And check the provider transcript before concluding a thing is unobservable —
it recorded the one `Skill` call the orchestrator's log did not.

## Bucket by the window, not by the day

A fixed daily bucket makes a 24-hour view a single point. An area chart of one
value is not a trend, and it looks like a bug because it is one. Scale the
bucket:

    <= 6h -> 15min, <= 24h -> 1h, <= 72h -> 3h, <= 14d -> 6h, else 1 day

Roughly 30-90 points keeps a stacked area legible. Floor in **local** time, and
floor daily buckets to local midnight rather than to a multiple of 86,400,000 ms
— the arithmetic version drifts off midnight in every non-UTC zone.

Fill empty buckets. Emitting only buckets that have data makes 24h, 7d and 30d
render identically whenever the data sits in one bucket, which reads as a broken
filter and gets reported as one.

## Verify against the numbers, not the picture

A frame capture can come back blank while the panel is genuinely painted — a
capture-path limitation, not a render failure. Distinguish them before you
conclude either way: check for an iframe, walk ancestors for opacity /
visibility / display / transform / filter / content-visibility, and call
`document.elementFromPoint()` at the mark's own coordinates. A region that is
not painted cannot return an element from a hit test.

Then verify what you actually can: hover each populated bucket and assert the
rendered tooltip values **equal the values the API returned**, bucket by bucket.
That catches wrong bucketing, wrong stacking and wrong scaling in one check, and
it does not depend on a screenshot.
