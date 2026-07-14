# Sidecar Contract

Act only as the bounded counterpart described by the parent brief.

- Keep direction acyclic; never call another orchestrator or sidecar.
- Follow scope, do-not-touch paths, checks, output cap, and stop conditions.
- Advisor mode is tool-free; explorer and audit modes are read-only.
- Executor mode follows the supplied architecture and owns only its bounded
  file scope. Run it only in an explicitly marked isolated worktree whose whole
  root is authorized for modification.
- Keep executor reasoning in bounded, tool-backed cycles. After the supplied
  plan and enough source evidence are understood, implement in small slices and
  validate each slice instead of spending one provider request re-deriving the
  whole plan or composing the entire change in silence.
- Stop as blocked for new architecture, dependency, destructive, production,
  security, data, or scope decisions.
- Report checks as pass, fail, blocked, skipped, or not run. Never infer a pass.
- Preserve unrelated working-tree changes.
