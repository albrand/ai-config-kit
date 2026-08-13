---
name: bb-plugin-authoring
description: >
  Use when writing or debugging a bb plugin — imports failing at load, a
  migration corrupting state, an RPC call rejected before it leaves the browser,
  or a build that works in a shell and not in bb.
verify: "test -f $HOME/.bb/plugins/fleet/data.db"
verified: 2026-08-12
---

# bb plugin authoring traps

## bb loads plugins through jiti, which breaks two things

- **Named imports from `node:` builtins fail.** `import { join } from "node:path"`
  resolves to undefined at runtime. Inline the helper instead — it is three lines
  and it always works.
- **Heavy bundled dependencies cannot be evaluated.** playwright-core dies with
  `Cannot read properties of undefined (reading 'join')`. Drive Chrome over CDP
  with the built-in WebSocket rather than pulling a browser automation library.

## The plugin server runs with a minimal PATH

`PATH=/usr/bin:/bin:/usr/sbin:/sbin`. No `node`, no `npm`, no homebrew. Consequences:

- ACP providers on a normal PATH are invisible to bb. Register them in
  `~/.bb/config.json` under `customAcpAgents` with an **absolute** command path,
  then `bb-app config refresh` (not `bb settings reload`).
- To drive the `bb` CLI from inside a plugin, spawn `process.execPath` with
  `ELECTRON_RUN_AS_NODE=1` and the CLI script path. A plain spawn fails.

## `MIGRATIONS` is append-only — the array index IS the migration id

Inserting a statement in the middle renumbers every later migration. This is not
enforced and it fails in two different ways, both quiet:

- If the inserted statement lands at an index the ledger already counts as
  applied, it is **skipped forever** — the table simply never exists, and
  nothing errors.
- If a later `ALTER` shifts into an unapplied slot it runs a second time:
  `duplicate column name: …`, and the plugin fails to load.

Append means the **literal end of the array**, not "next to the related table"
where it reads better. Both mistakes here came from tidiness.

There is no in-place repair. A ledger keyed by position cannot be corrected by
editing the statement at that position — if a slot was consumed by a different
statement, append the intended one again. `IF NOT EXISTS` makes the duplicate
harmless.

After any migration change, verify the table exists rather than trusting a clean
reload: `sqlite3 <db> "select name from sqlite_master where name='<table>'"`.

## `undefined` in an RPC payload is rejected client-side

`rpc input at $input.query is not a JSON value`. No network request, no console
error, no server log — it looks like the handler is broken. Omit optional keys
entirely rather than setting them to `undefined`.

## Storage is isolated per plugin

Each plugin gets its own directory under `~/.bb/plugins/<name>/data.db`. One
plugin cannot read another's tables. To share, expose a local HTTP route
(`bb.http.route`, `auth: "local"` — the path needs a leading slash) or an RPC.

## Plugins can ship skills

`"bb": { "skills": ["skills"] }` in `package.json`, with each skill at
`skills/<name>/SKILL.md`. bb loads them automatically.

## Two more that cost real time

- **`bb.agents.configure` resolves at session start**, before any tool registered
  later exists. An agent spawned by your plugin can be born unable to see your
  plugin's tools.
- **HTTP handlers receive a Hono context, not a `Request`.** Read query params
  with `c.req.query("name")`.
