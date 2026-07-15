# Worktree Ownership Reference

Git worktrees are the **only** write-isolation boundary in this skill. The rule
is one task, one worktree, one write owner.

## Lane Creation

- Validate the repo path is absolute and resolves inside the repo root. Reject
  traversal (`..`) and symlink escapes.
- Validate the repo is a git work tree and the base branch exists.
- Validate the slug against `^[a-z0-9][a-z0-9-]{0,62}$`. The branch is
  `cmux-hermes/<slug>` and the worktree lives under
  `<repo>/.cmux-hermes-worktrees/<slug>`.
- If the worktree path already exists, fail: never auto-overwrite or auto-delete.
- `--dry-run` validates and reports the plan without creating anything.

## One Owner Lock

- Before external side effects, the broker validates the task ID and atomically
  reserves `<task>.lock` with `O_EXCL`; collisions fail closed.
- On creation, the broker writes `<task>.lock` (mode `0600`) recording a hash of
  an unguessable one-time owner capability, worktree, and acquisition time, and
  a task manifest (mode `0600`) recording
  task id, cmux workspace/surface UUIDs, Hermes session, repo, worktree, branch,
  role, model, budget, status, artifacts, and timestamps.
- Lane creation stores the capability in a random `0600` file and prints only
  its path; the secret never appears in argv or shared terminal output.
  `cancel`, `close`, and `cleanup` require `--owner-capability-file`. This
  prevents accidental cross-thread mutation but is not an adversarial boundary
  between processes sharing the same Unix UID.
- Directories holding manifests/locks are mode `0700`.

## Cancel And Close

- `cancel` stops/closes cmux and Hermes sessions and marks the task cancelled. It
  **never** deletes the branch or worktree.
- `close` marks the task closed and preserves branches and worktrees.

## Cleanup (Report-Only By Default)

- `cleanup` with no flags is **report-only**: it reports whether the worktree is
  clean (`git status --porcelain` empty) and the branch is merged
  (`git branch --merged <base>`).
- Destructive removal requires **explicit `--force`** and proof that the worktree
  is clean **and** the branch is merged.
- If the proof is unreliable, the destructive step is omitted and the worktree and
  branch are left intact.

## Defaults

Concurrency 1, depth 1, delegation disabled unless explicitly enabled per task.
No task may write outside its own worktree.
