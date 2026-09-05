# bb Adapter

Thin bootstrap for the bb agent harness. Copy this file into the target
workspace as `.bb/AGENTS.md` and keep the installed framework under a stable
path such as `docs/agent-framework/` (adjust the imports if the path differs).
This file points at the framework instead of forking it and does not repeat
global guardrails.

## Bootstrap

1. Load `docs/agent-framework/CORE.md` as the always-on baseline.
2. Load only the task-relevant docs named by CORE.md's "When To Load More"
   (or the installed router skill). Do not read the whole README or manifest
   by default.
3. Follow the active provider's instruction hierarchy. This bootstrap supplies
   repository defaults; the current user request defines task scope within that
   hierarchy.

## bb discovery facts

- bb injects its data-dir `AGENTS.md` and the workspace `.bb/AGENTS.md`
  itself; there is no parent-directory walk for those bb-specific locations.
- Skills load from `.bb/skills/<name>/SKILL.md`. Project skills take
  precedence over user skills, which precede builtins; same-source duplicate
  names collide and are dropped. Native provider instruction paths are
  separate from these bb locations.
- Inspect live configuration with `bb guide agent-configuration` and
  `bb skill list --environment <id> --json` instead of assuming.

## Lifecycle and models

Use bb's own surfaces, not terminal injection: `bb status` for lifecycle
state, the provider's model listing for available models, and bb's thread and
environment selectors for delegation targets. Verify that a provider, model,
or agent exists before routing work to it; availability never authorizes
scope expansion.

## Scope

Treat the complete user request and its accepted revisions as the task's
scope. `docs/agent-framework/SCOPE_DISCIPLINE.md` owns the scope record,
necessary-versus-optional classification, and the bounded scope-advisor
protocol. For substantial ambiguity, complex delegation, or suspected drift,
use the installed `scope-advisor` skill
(`.bb/skills/scope-advisor/SKILL.md`) as a read-only check; the coordinator
stays responsible.
