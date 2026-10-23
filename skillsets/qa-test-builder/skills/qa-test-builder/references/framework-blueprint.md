# Framework blueprint

This is the design of the QA layer, not code to copy. Write it for the
repository in front of you: match its language, folder conventions, Node
version and size. A small repository gets a small layer. Reuse whatever already
exists (a Playwright config, a reporter, a CI job) instead of adding a second
one.

## Pieces

```
qa/
  qa.config.json            what the layer needs to know about this repository
  policy.json               the rules the gate applies (read from the main branch in CI)
  requirements/<KEY>.json   ticket snapshots (ticket-reading.md)
  clarifications/<KEY>.json QA answers (ticket-reading.md)
  scenarios/<KEY>.json      the designs (scenario-design.md)
  tools/qa.mjs              the QA command: check, plan, run, gate, report
<tests folder>/             the Playwright tests (e2e/qa/ or tests/qa/ in an app repo)
playwright.config.ts        or a QA project inside the existing one
```

Write the QA command in plain JavaScript (`.mjs`) with no dependencies beyond
Node itself. CI runs it from a clean checkout of the main branch, before and
without installing anything from the pull request, so it must not need a build
or `npm install`. Node 20 or newer is enough. Playwright, Allure and TypeScript
belong to the test project, not to this command.

In a repository that is not Node-based (.NET, Python, Go, Java), put a
`package.json` and lockfile for Playwright and Allure in `qa/` (with the tests
under `qa/tests/`), so nothing touches the app's own build.

## qa.config.json

```json
{
  "board": { "provider": "jira", "url": "https://example.atlassian.net", "keyPattern": "PROJ-[0-9]+" },
  "testsLocation": "same-repo",
  "appRepository": "owner/app",
  "testsRepository": "owner/app",
  "tests": { "root": "e2e/qa", "config": "playwright.config.ts", "projects": ["chromium"] },
  "app": { "kind": "frontend", "start": "npm run dev", "url": "http://127.0.0.1:3000", "health": "/" },
  "allure": { "results": "allure-results", "report": "allure-report" },
  "qaTeam": "owner/qa"
}
```

- `testsLocation`: `same-repo` or `separate-repo`, the QA's answer from Phase 1.
- `app`: how the tests reach the app. For a frontend with mocked API, the dev
  server. For a backend, the command that starts the API for tests, the URL and
  a health path. For a deployed environment, only the URL (never production).
- `qaTeam`: the GitHub team whose members' authorship or approval makes a
  scenario QA-approved (`qa-authorship.md`).

## policy.json

```json
{
  "baselineScopes": ["regression", "smoke"],
  "retries": 2,
  "flaky": "block",
  "nonBlockingStatuses": ["awaiting-implementation"],
  "allowedBaseUrls": ["http://127.0.0.1", "http://localhost"],
  "requireQaApproval": true
}
```

It lives in the repository and CI reads it from the main branch, so a pull
request cannot loosen the rules that judge it.

## The QA command

### `check`

Fails, with a message a QA can act on, when:

- a scenario ID is duplicated or malformed;
- a criterion has neither a scenario nor a decision;
- a scenario cites a criterion that no longer exists, or the requirement's
  revision changed since the design (the scenario must be reviewed);
- a bound scenario's file is missing or has no test tagged with its ID;
- a test in the QA folder has no scenario tag, more than one, or an unknown one;
- a QA test uses `.only`, `.skip`, `.fixme`, `.fail`, or a fixed wait
  (`waitForTimeout`, `sleep`);
- the pull request removes an assertion from a QA test without changing that
  scenario's `expected` in the same pull request.

### `plan`

Input: the pull request's title, branch name and body, and the base branch.

1. Find ticket keys with `board.keyPattern`. Count a key only when it is clearly
   the subject (in the title, the branch name, or a "Closes/Fixes/Ticket"
   line), not a passing mention.
2. Mandatory scenarios: those of the named tickets with scope `feature`, plus
   every `regression` and `smoke` scenario that is `ready` on the base branch.
3. Write `qa-reports/plan.json`: the tickets, the mandatory scenario IDs with
   their status, and the grep pattern for the runner.

No ticket named means a plan with only the baseline and `tickets: []`.

### `run`

Runs Playwright with the plan's grep (`--grep "@QAS-A|@QAS-B"`), the configured
projects, `--retries` from the policy, and three reporters: `list` for the log,
`json` to `qa-reports/results.json` for the gate, and `allure-playwright` to the
Allure results folder. A failing test must not stop the job before the gate.

### `gate`

Reads the plan and the results, and writes `qa-reports/verdict.md` and
`qa-reports/verdict.json`. For each mandatory scenario: `passed`, `failed`
(with the first error line and the test title), `flaky` (passed only on a
retry), `not-run` (no test ran for it), or `awaiting` (non-blocking status).
The verdict is the first that applies:

| Verdict | When | Exit |
|---|---|---|
| `FAILED` | any mandatory scenario failed, did not run, or is flaky under `flaky: block` | 1 |
| `NO_SCENARIOS` | a named ticket has no scenarios and no decisions | 1 |
| `UNAPPROVED` | everything passed, but a feature scenario is not QA-approved | 0 |
| `NO_TICKET` | no ticket named; only the baseline ran and passed | 0 |
| `VERIFIED` | tickets named, all their scenarios passed and are QA-approved | 0 |

The first line of `verdict.md` is `# QA gate: <VERDICT>`, then a table of
scenarios with result, ticket and test title, then the failures with their
error lines. The approval job in CI reads this file.

### `report`

Generates the Allure report from the results folder into the report folder
(`allure.md`). It never fails the job; the gate alone decides.

## Commands the QA will use

Add short scripts so the QA never needs to remember flags:

| Script | Does |
|---|---|
| `qa:check` | `node qa/tools/qa.mjs check` |
| `qa:test` | runs the QA tests for one ticket: `node qa/tools/qa.mjs run --ticket PROJ-123` |
| `qa:local` | plan for the current branch, run, gate, report, open the report |
| `qa:report` | `allure open allure-report` |

Put them in the `package.json` that owns Playwright. Document them in a short
`qa/README.md`: what each command does, where scenarios live, and how to read
the gate's verdict. That file is for the QA, so keep it in plain language.

## Starting the app for tests

Use Playwright's `webServer` so the same config starts the app locally and in
CI:

- **Frontend, mocked API:** the dev server or the built app's start command.
  Mock every network call the screen makes in the test; any call the test does
  not handle should fail loudly, not reach a real server.
- **Backend:** the command that runs the API on a local port, with a test
  configuration. Prefer an in-process or file database (SQLite) or a CI
  service container with the migrations applied. Seed one user per role the
  scenarios need, with synthetic credentials kept in test config or CI secrets,
  never real accounts. Stub everything that leaves the process (email, storage,
  payments, scanners) the way the developers already do in their tests. If the
  app has no switch for that, the developers must add one: say so.
- **Deployed environment:** only a non-production URL from `allowedBaseUrls`.
  The run refuses any other URL.

## Ignore and commit rules

Add to `.gitignore`: `allure-results/`, `allure-report/`, `qa-reports/`,
`test-results/`, `playwright-report/`. Commit the lockfile.
