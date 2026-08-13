---
name: bb-sdk-traps
description: >
  Use when calling the bb plugin SDK — listing providers or threads, reading
  thread events, spawning threads on a machine, or creating worktrees. Several
  calls return confident, wrong-looking-right answers; this is what each one
  actually does.
verify: grep -c "providerCliStatus" {{BB_PLUGIN_SDK_TYPES}}
verified: 2026-08-12
---

# bb SDK calls that mislead

Each of these was found by a wrong result reaching production, not by reading
docs. They cost hours; none announce themselves.

## `providers.list` is a declaration, not a probe

It reports every provider bb *knows about* with `available: true`, including on a
machine where the CLI was never installed. Routing work off this list places it
on a machine that cannot run it.

Use **`hosts.providerCliStatus({hostId})`** → `installed: true | false`. It runs a
real check. It covers only `codex`, `claudeCode` and `cursor` (camelCase keys);
custom ACP agents live in that machine's own config and cannot be verified
remotely, so treat them as unusable on a machine you do not control.

`system.usageLimits({hostId})` *is* genuinely per-machine and safe to trust —
verified by claude-code reporting `ok` on one host and `unauthenticated` on
another in the same call pattern.

## `threads.events.list` pages at 100

One call never catches up a live thread. Page with `afterSeq` until the returned
max sequence stops advancing.

Worse: **`limit` without `afterSeq` returns the OLDEST events, not the newest.**
A "start at the tip" shortcut silently started at event 533 of 5414. There is no
tip shortcut — page from zero.

## `threads.list()` is not complete

Unscoped it returned 3 threads where the CLI returned 5. `projects.list()` omits
the personal project entirely, so personal-project threads are reachable *only*
through the unscoped call. Union both:

```ts
for (const projectId of [undefined, ...projectIds]) { /* list, merge by id */ }
```

Passing `archived: "false"` made coverage worse, not better. Pass no filter.

## Spawning: three separate rejections

- **Worktree schema.** The `managed-worktree` union member takes
  `baseBranch: { kind: "default" | "named" }`. Passing `branch` (which belongs to
  the `unmanaged` member) fails with the unhelpful `HTTP 400: Required`.
- **A managed worktree needs a git repository.** bb discovers this only at
  provisioning time and fails the whole thread with `Path is not a git
  repository` *after* accepting the spawn. Check first with
  `hosts.pathsExist({hostId, paths: ["<path>/.git"]})`.
- **`parentThreadId` must be live and in the same project.** Cross-*project*
  parenting fails with `Parent thread is invalid`; cross-*machine* parenting is
  fine. An **archived** parent fails the same way — so an orchestrator thread
  that gets archived silently breaks every later spawn in its group.

A host also needs a project source (`project.sources[]` matching that `hostId`)
or the spawn returns `HTTP 409`.

## Background services

`bb.background.service(name, { start: async (signal) => {...} })`. There is no
`intervalMs`/`run` form — that shape fails the plugin reload with
`must provide a start(signal) function`.
