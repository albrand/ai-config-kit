# Project Setup (Manifest-First, Reuse-First)

This reference defines how an agent sets up a project workspace on a native
agent surface: **manifest-first** (describe intent) and **reuse-first** (discover
an existing workspace before creating one). cmux is the worked example; the same
shape applies to other adapters via `resolve-workspace.py`.

## Principles

- **Manifest-first.** Read the repo's declared setup (manifest, README, lock
  files, build/test commands) before running anything. Never guess a project's
  commands from the binary or shell history.
- **Reuse-first.** Before creating a workspace, resolve the structured runtime
  inventory: an exact existing workspace (cwd == project) is reused; a single
  inside-project workspace is eligible; a broad-parent cwd is advisory only and
  is never auto-reused; ties/duplicates are ambiguous and fail closed.
- **Never auto-create on top of ambiguity.** Ambiguity is a stop condition.

## Setup flow

1. Detect surfaces: `scripts/detect-native-surfaces.py --format json`.
2. Confirm the surface you need is `available` and offers the capability.
3. Produce the structured inventory (adapter-owned, argv-only JSON output).
4. Resolve reuse: `scripts/resolve-workspace.py --project <abs> --surface cmux
   --inventory <json-or-->`.
5. If `decision == reuse`, attach to the `selected` workspace (full UUID).
6. If `decision == missing`, create exactly one non-focused workspace, then
   re-validate the returned UUID and post-create identity (the new UUID must
   appear in a fresh inventory pointing at the project cwd).
7. If `decision == ambiguous`, stop and report; do not create.

## Project bootstrap and run discovery

After selecting the workspace, derive the setup from repository truth in this
order. Record the chosen commands and their source in the task manifest.

1. Resolve the git/workspace root and load all applicable `AGENTS.md` files.
2. Inspect README/setup docs, language manifests, lockfiles, version files,
   workspace manifests, container/devcontainer files, and example env schemas.
3. Select the package manager from the lockfile; never substitute another one.
4. Inventory existing processes and listening ports in the selected workspace.
   Reuse a healthy server for the same root and command; do not start a second
   copy merely to obtain a new terminal.
5. Run the documented dependency/setup command. Do not invent secret values;
   report missing required configuration by variable name only.
6. Run the smallest deterministic health check, then the documented unit,
   integration, and E2E entry points applicable to the change.
7. If a dev server is required, start one owned process, wait on an explicit
   URL/health condition, and record its workspace, surface, PID/process handle,
   port, command, and ownership. Never kill an unowned process.
8. Hand the verified base URL and browser-surface identifier to the browser E2E
   flow. On teardown, close only resources created by this task.

If manifests conflict, commands are missing, or an existing server cannot be
attributed to the project, stop at a named breakpoint rather than guessing.

## Server / persistent-surface reuse

- Persistent surfaces (e.g. a Hermes master tmux session) are reused, not
  re-spawned per task: check existence before create, and refuse to detach or
  tear down while children are running.
- One task creates at most one workspace; one writer owns a worktree.

## Hard boundary

- Never serialize environment values or `CMUX_*`. Persist full UUIDs only.
- Never execute a discovered binary during discovery; presence is not trust.
- Project paths must be absolute and canonical; reject relative/traversal input.
