---
name: verify
description: >
  Use in any repo, new or legacy, to decide whether a change works and to bring the repo up to
  standard. `doctor` audits what is missing (tests, journeys that walk the real app, evals for
  LLM output, dry runs for data-moving code, mutation testing, CI). `init` writes the repo's
  definition of done. `run` executes it and reports pass, fail or NOT VERIFIED per stage.
  `serve` is a self-hosted runner that needs no GitHub Actions. Use before reporting work done,
  when onboarding or cleaning up a repo, and when a test suite looks green but users still hit bugs.
verify: 'python3 -m unittest discover -s "$HOME/.agents/skills/verify/scripts/tests"'
verify_timeout: 120
verified: 2026-10-06
---

# verify

One definition of done per repo, in `.verify/config.json`, run the same way by every agent,
every human and the runner. Results are advisory commit statuses. Nothing here blocks a merge
or a deploy.

```
V=~/.agents/skills/verify/scripts/verify.py
python3 $V doctor .            # what is missing, by severity, with the fix
python3 $V init . --write      # propose .verify/config.json from the stack
python3 $V run . --strict      # run every per-change stage; artifact in .verify/runs/<sha>.json
python3 $V status .            # last result for HEAD
```

## Done means

`run` is green only when every stage is `pass` or `na` with a written reason. A stage with no
command is `missing`, which reports **NOT VERIFIED** and names the stage. That is a status, not a
stopping point: write the missing stage if you can, then run it.

| Stage | Proves | Template |
|---|---|---|
| static | it builds, lints, typechecks | — |
| unit | the logic users depend on | — |
| integration | real database, queue, cache; no in-memory fakes | [README](templates/README.md#integration) |
| journeys | a persona walks through the running app, frontend and backend, as a user would | [journeys](templates/journeys/README.md) |
| evals | LLM output quality, measured over repeated runs (pass@1, pass^k, per-label recall) | [evals](templates/evals/README.md) |
| rehearsal | backfills, crons and workers do the right thing on production-shaped data (read-only dry run) | [README](templates/README.md#rehearsal) |
| mutation | the tests catch injected bugs (scheduled, changed files only) | [mutation](templates/mutation/README.md) |
| postdeploy | the deployed URL is healthy and the @smoke journeys pass there | [postdeploy](templates/postdeploy/README.md) |

## Rules that keep the result honest

- Strict mode (the runner always uses it): a required env var that is missing fails the stage
  instead of letting the suite skip itself, and more skips than `max_skipped` fail it.
- Journeys hit the real backend. Blocking third-party origins is fine. Answering the app's own
  API with `route.fulfill`, msw or nock belongs in a component test, and `doctor` flags it.
- `weaken-check` fails a change that deletes tests, adds skip/only, removes assertions or edits
  expected values, unless a commit says `test-change-reason: <why>`.
- Non-deterministic output is scored, not eyeballed: `eval-score --dataset --predictions`.
- Production data is read only through the rehearsal stage, and only after the owner has
  approved the source and the masking.

## Bootstrapping a repo

1. `doctor .`, then `init . --write`. Commit `.verify/config.json`.
2. Fill each `todo` stage from its template, highest severity first. Mark a stage `na` only with a
   reason that is true today.
3. `housekeep .` lists merged branches, stale worktrees, large and cache files. `--apply` only
   deletes merged local branches and prunes worktree records.
4. Copy [templates/AGENTS.repo.md](templates/AGENTS.repo.md) to the repo's `AGENTS.md` and fill it in.
5. Runner, on a machine you control: `verify.py serve --repo OWNER/NAME` (add `--once` to a cron
   or bb automation). It runs open PR heads in throwaway clones and posts `verify/<stage>` statuses.
   Owner-chosen branches (`--branch develop`) also run `mutation` when it has a command.
   - PR code is untrusted. A PR runs its base branch's `.verify/config.json`, so it can't change what
     is checked. A PR that adds the first config gets `missing` until that config is merged.
   - Every command a repo controls runs in a macOS `sandbox-exec` profile. It can't read `/Users`,
     `/Volumes`, `/tmp` or `/var/folders`, apart from its job dir and toolchains (`--allow-read`
     adds one, e.g. a shared `node_modules`). It writes only its job dir. It can't reach the
     keychain, the ssh-agent, Docker, or any port listening on the host when the job started
     (`--allow-host-port` opens one, e.g. a test database). There is no supported sandbox
     elsewhere, so the runner refuses to run PR code; `--unsandboxed` is for disposable machines.
   - Jobs get an allowlisted environment, with HOME and TMPDIR inside the job, and forge tokens
     never reach them. Network egress stays open (installs and journeys need it), so PR code can
     send anything it sees. That is why PR jobs get no secrets. Values go in
     `~/.cache/verify-runner/env/`, never in the repo:
     - `<owner>__<name>.pr.env`: what every PR author may read, such as a throwaway local test
       database or a seeded test persona. PR jobs get only this.
     - `<owner>__<name>.env`: secrets. Only `--branch` jobs, which run merged code, get them. A
       job counts as a branch job only if its commit is, at that moment, the head of a branch the
       owner listed. List only branches PR authors can't push to directly.
     - Forks get neither, and a PR that doesn't say whether it is a fork counts as one. A PR whose
       base branch is missing or unknown doesn't run. Values are masked in statuses and run records.

## Hook

`verify.py hook` is a PostToolUse hook for Claude Code and Codex (same schema). After a merge,
deploy or protected push in a repo that has `.verify/config.json`, it adds the commit's verify result
to the agent's context and, unless it passed, asks the agent to run verify and fix what fails. In repos
without a config it says nothing. It never denies.
