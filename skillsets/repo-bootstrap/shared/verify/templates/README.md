# verify templates

Each stage in `.verify/config.json` is a shell command plus a few options:

```json
{
  "setup": "pnpm install --frozen-lockfile",
  "stages": {
    "integration": {
      "run": "pnpm run test:integration",
      "env": ["DATABASE_URL"],
      "services": "docker compose -f compose.test.yml up -d --wait",
      "stop": "docker compose -f compose.test.yml down -v",
      "max_skipped": 0,
      "paths": ["src/**", "test/integration/**"],
      "timeout": 900
    },
    "evals": { "na": "no LLM features" }
  }
}
```

`env` names variables the stage needs; in strict mode a missing one fails the stage. On the runner
they come from its env file, and forge tokens never do. `paths` limits a stage to changes that touch
those globs (otherwise `untouched`). `na` needs a reason.

On the self-hosted runner, stages are sandboxed and can't reach the Docker socket or ports already
listening on the host. So `services` that call `docker compose` work locally but not there. On the
runner machine, keep the test database running yourself and pass `serve --allow-host-port <port>`.
Services the stage starts as its own processes work in both places.

## integration

Integration tests talk to the same kind of database, queue and cache that production uses, started
for the test run, not mocked and not in-memory substitutes.

- Start dependencies in `services` (Docker Compose with `--wait`, or Testcontainers inside the
  tests). Tear them down in `stop`.
- Each test creates its own data and cleans it up, so tests can run in any order.
- Name every variable in `env`. A suite that silently skips when `DATABASE_URL` is unset is the
  most common way a red build turns green; strict mode stops that.
- Cover what unit tests cannot: migrations applied to a real schema, transactions, unique and
  foreign-key constraints, query shapes, and the job or webhook that writes what a screen reads.

## rehearsal

Code that moves data (backfills, migrations, crons, queue consumers, sync jobs) gets a dry run on
production-shaped data before it ships. A dry run reads, computes and reports; it never writes.

1. Give the job a `--dry-run` flag (or a separate entry point) that runs the real code path and
   replaces each write with a recorded intent: table, key, before, after.
2. Point it at a read-only source. Prefer, in order: a masked snapshot, a read replica with a
   read-only role, then production through a read-only role. The owner chooses the source and
   approves masking of personal data before the first run. Credentials come from the runner's env
   file, never the repo.
3. Print a summary the stage can judge: rows read, rows that would change, rows that would be
   skipped and why, errors. Exit non-zero on errors, or when the change count is outside the
   expected range stored next to the job (for example `expected.json`: `{"max_changes": 500}`).
4. Config: `"rehearsal": {"run": "node scripts/backfill.js --dry-run", "env": ["REPLICA_URL"],
   "paths": ["src/jobs/**", "scripts/backfill*"]}`.

A rehearsal that cannot reach its source fails in strict mode. It does not pass by skipping.
