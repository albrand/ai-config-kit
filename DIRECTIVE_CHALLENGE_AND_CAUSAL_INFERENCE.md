# Directive Challenge And Causal Inference

This framework treats every directive, memory, journal, cached conclusion, and
prior project pattern as evidence to test, not authority to obey blindly.

That rule exists because AI-assisted work can fail in a specific way: the agent
can build a persuasive causal story from the wrong evidence. A past journal, a
successful pattern from another repository, a global instruction, or a model's
pretrained habit can all look like proof. They are not proof. They are signals
that must be checked against the current task, current repository, current
runtime, current board, and current acceptance criteria.

## The Problem

Software work is full of confounding variables.

A confounder is a factor that makes one explanation look causal when another
factor is actually driving the result. In agent workflows, common confounders
include:

- A prior decision that worked in one repository but depended on that repo's
  stack, team rules, data model, deployment platform, or release process.
- A journal entry that recorded the visible fix but not the hidden constraint
  that made the fix safe.
- A cached summary that was correct before a branch, dependency, schema, or
  ticket changed.
- A global directive that improves most work but conflicts with a stricter
  repo-local rule.
- A pattern found in a sibling project that solves a similar-looking problem but
  under different auth, data, tenancy, or performance constraints.
- A model habit learned from common public code that does not match the current
  codebase's architecture.

Without a challenge step, the agent can overfit to those signals. It may explain
the current problem using the most familiar prior cause, then implement a
plausible fix that does not actually address the current system. This is the
causal overfitting risk the framework is designed to control.

## The Rule

The directive challenge has five parts.

1. Treat prior evidence as useful but provisional.
   Journals, memories, directives, cached conclusions, and previous project
   patterns are a fallback training base. They help the agent start faster, but
   they do not outrank current evidence.

2. Preserve source-of-truth precedence.
   The challenge loop does not weaken safety, the current user request, repo
   instructions, tests, runtime behavior, board acceptance criteria, or live
   deployment facts. It asks whether older or broader guidance still fits those
   sources.

3. Use an independent critique for non-trivial planning and architecture.
   When planning or architecture materially affects behavior, security, data,
   release, or broad implementation shape, route a critique through another
   model or counterpart when available. If no counterpart is reachable, run a
   local self-critique and report the fallback.

4. Scan reusable patterns only through configured workspace roots.
   Cross-project scans must use roots configured by the repo, harness, explicit
   user input, or variables such as `AGENT_WORKSPACE_ROOTS`. A personal
   `~/projects` path is not portable framework truth. Pattern scans stay
   metadata-first, budgeted, and secret-free until there is a concrete reason to
   inspect code.

5. Verify fit before adopting.
   A discovered pattern is a candidate, not a template. It must match the
   current stack, architecture boundaries, data model, auth model, tests, quality
   gates, and acceptance criteria before use.

## Examples

### Prior Journal Confounder

A journal says a previous auth bug was fixed by changing token refresh timing.
The current auth bug has the same symptom: users get logged out. Without a
challenge, the agent might adjust refresh timing again.

The challenge asks what else changed. Current evidence shows the route now runs
behind a different proxy and drops a cookie attribute. The old journal was
useful because it suggested where to inspect, but it was not causal proof.

Gain: the fix targets the current runtime boundary instead of repeating an old
solution.

### Sibling Project Pattern Confounder

A sibling project has a clean queue worker abstraction. The current project also
needs background processing. Copying the abstraction looks efficient.

The challenge checks fit: the sibling project runs isolated jobs with no tenant
state, while the current project needs tenant-scoped authorization, audit logs,
and idempotent retries. The abstraction can inspire the shape, but the current
repo needs stricter boundaries.

Gain: useful reuse without importing an unsafe assumption.

### Global Directive Confounder

A global directive says to use a delegated executor for implementation. The
current task touches a migration with data-loss risk. Blind delegation would move
too much judgment away from the coordinator.

The challenge preserves the directive's intent but scopes it: keep architecture,
data-loss analysis, rollback, and final validation in the master thread; delegate
only bounded discovery or mechanical edits with clear stop conditions.

Gain: delegation improves coverage without weakening ownership.

### Model Habit Confounder

The model has seen many projects use a popular library for form validation. The
current repo already has a smaller validation helper and strict bundle limits.

The challenge asks whether adding the familiar library is actually better. The
repo evidence says no: the existing helper covers the case and avoids dependency
churn.

Gain: industry-quality standards are applied through the current repo's
constraints, not through generic popularity.

### Personal Path Confounder

One operator keeps repositories under `~/projects`. Another uses a monorepo
workspace, a mounted volume, or a company-managed checkout path.

The challenge forbids hardcoding the first operator's layout into shared
framework instructions. Portable guidance says to resolve configured workspace
roots first, then scan only those roots.

Gain: the framework remains generalist and safe for other users.

## What Improves

The directive challenge improves quality in practical ways:

- Fewer false root causes because prior conclusions must be re-tested.
- Fewer regressions because accepted behavior and board-backed criteria stay in
  the evidence loop.
- Better architecture decisions because another model or counterpart pressures
  the plan before execution.
- Better pattern reuse because cross-project scans identify candidates without
  copying incompatible assumptions.
- Better portability because user-specific paths, tools, and account details are
  kept out of shared framework truth.
- Better context hygiene because journals and memories become compact training
  evidence instead of stale commands.
- Better validation reporting because the agent must state what was verified,
  what was inferred, and what remains blocked.

## What This Is Not

This is not endless skepticism. The challenge loop is bounded and evidence-led.
It should not block small, obvious work or turn every answer into an academic
essay.

This is not a reason to ignore instructions. Higher-priority safety rules,
current user instructions, repo-local requirements, tests, runtime behavior, and
accepted criteria still control the work.

This is not permission to scan private systems broadly. Cross-project pattern
searches stay metadata-first, secret-free, and limited to configured workspace
roots.

The point is disciplined self-improvement: every prior lesson remains available,
but every prior lesson must prove it still applies.
