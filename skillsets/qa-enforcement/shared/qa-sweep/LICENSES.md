# Licenses and attributions

This skill adapts material from three public skill collections. No upstream
code is vendored; the workflow structure and specific disciplines were
adapted, with the changes listed below. Full license texts at the linked
repositories.

## vercel-labs/agent-browser — skill-data/dogfood/SKILL.md (Apache-2.0)
Copyright Vercel Labs. Adapted for P1 (walk + inventory, evidence-per-defect,
append-immediately, never delete output, test like a user). Deliberate
changes: (1) REMOVED the "aim for 5-10 well-documented issues, then wrap up"
cap — the walk covers the entire workflow to its outcome; (2) replaced the
`agent-browser` CLI with the bb `browser_*` tools; (3) added the
predates-change column to every inventory row. License:
https://github.com/vercel-labs/agent-browser (Apache-2.0)

## obra/superpowers — systematic-debugging, verification-before-completion (MIT)
Copyright Jesse Vincent (obra). Adapted for P2/P4: root-cause hypothesis
before any fix, consistent reproduction before diagnosis, a repro that must
fail once before it is trusted, and verification-before-completion semantics
for the P5 re-walk. https://github.com/obra/superpowers (MIT)

## mattpocock/skills — engineering/diagnosing-bugs (MIT)
Copyright Matt Pocock. Adapted for P2: read the error completely, reproduce
first, minimal repro per cluster, hypothesis stated as a causal story.
https://github.com/mattpocock/skills (MIT)
