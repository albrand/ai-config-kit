# Builder.io Provenance Reference

This skillset adapts public engineering concepts from Builder.io with attribution
and license fidelity. It does not copy unlicensed material.

## Source Of Record

- Repository: `BuilderIO/skills`
- Commit: `d1344bc088f850f829d9bcf4170516bb670a438f`
- License: MIT (full text bundled with the `plan-arbiter` skill at
  `codex/plan-arbiter/references/builderio-mit-license.md`).

## Adapted Concepts

The following ideas are adapted into neutral framework language, not copied:

- **Plan arbitration** — arbitrate between competing plans/lanes on evidence and
  capability rather than first past the post.
- **Efficient frontier** — hand work to the lane that offers the best
  quality/cost/latency trade-off for the task shape.
- **Agent watchdog** — verify delegated results independently before accepting them.
- **Stay within limits** — check budget (turns, output, tokens, concurrency) before
  each bounded wave and stop when exhausted.

## Excluded Material

- `BuilderIO/skills` `agent-native` commit `879406d2fa4a644f1198e9f84b8afaed5dda903c`
  had **no confirmed license**. Concepts may be independently described, but no
  code or text is copied from it.
- Do not use an `@latest` installer or any auto-updating fetch of upstream content.
- Do not copy unlicensed agent-native implementation text or code.

## Policy

Keep adaptations source-traceable and small. Record the commit hash and license
wherever a Builder.io concept is used. Challenge any cached pattern for current
fit rather than treating it as authority.
