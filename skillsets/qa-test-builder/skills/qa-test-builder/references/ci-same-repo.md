# CI when the tests live in the app repository

Examples use GitHub Actions. On another CI system, keep the same jobs, trust
boundary and outputs, and translate the syntax.

Pin every action to a full commit SHA with the version in a comment, and use
the runtime versions the repository already pins.

## Workflows

### 1. `qa-gate`: run and judge

Triggers: `pull_request` with types `opened, synchronize, reopened, edited,
ready_for_review` (`edited` so a ticket added to the title or body re-plans; run
on drafts too, so QA see results early). Add `merge_group` if the repository
uses a merge queue.

Permissions: `contents: read`, `pull-requests: read`.

Steps:

1. Check out the pull request with full history.
2. **Trusted tools:** check out the base branch into a separate folder
   (`git worktree add --detach "$RUNNER_TEMP/qa-trusted" origin/<base>`). Run
   `qa.mjs` and read `policy.json` from there. If the base has no QA tools yet
   (the pull request that adds them), say so and pass: the gate starts with the
   next pull request.
3. Install the test project's dependencies from the pull request (`npm ci`),
   and Playwright's browsers, or use the official Playwright container image of
   the same version.
4. Start what the tests need (database service, the API) if the Playwright
   config's `webServer` does not.
5. `check`, then `plan` with the pull request's title, branch and body passed
   through environment variables (never interpolated into the script, which
   would let a pull request title run shell commands).
6. `run`, allowed to fail (`continue-on-error: true`).
7. `gate`: this step's result is the check's result.
8. Always: append `verdict.md` to the job summary, upload `qa-reports/` and
   `allure-report/` (after `report`) as artifacts, and upload `verdict.md` alone
   as a small artifact for the comment job.

Name the job `qa-gate` and make it a required check on the main branch (the
repository owner does this in branch protection or rulesets).

### 2. `qa-gate-report`: comment on the pull request

A second job in the same workflow, `needs: qa-gate`, with
`pull-requests: write`. It does not check out code. It downloads the verdict
artifact and creates or edits one comment on the pull request, marked with an
HTML comment such as `<!-- qa-gate-report -->`, holding: the headline (the
gate job's own result, so an edited file cannot turn a failure green), the
commit, the run link, the Allure artifact link and the verdict body. Skip pull
requests from forks: their token is read-only.

### 3. `qa-approval`: approve or request changes

Triggered by `workflow_run` of `qa-gate` (types `completed`), so it runs with
the base branch's workflow file and a write token even for pull requests that
cannot be trusted. It never checks out or runs the pull request's code. It
downloads the verdict artifact from the triggering run and acts on the pull
request whose head SHA matches that run:

It also publishes the `qa-authorship` check (`qa-authorship.md`).

| Gate result, verdict and authorship | Action |
|---|---|
| success, `VERIFIED`, tickets named, `qa-authorship` passed | Approve: "QA tests for PROJ-123 passed at `<sha>`", with the run link |
| failure | Request changes, listing each failed scenario with its test title and first error line, and the run link |
| success, but `NO_TICKET`, or `qa-authorship` failed | No approval. Dismiss this bot's earlier approval if there is one, with the reason |
| the pull request changes the QA workflows, `qa/tools/` or `qa/policy.json` | No approval, and dismiss an earlier one: a change to the rules needs a human review |

Everything read from the triggering run's artifacts (scenario titles, error
lines) is untrusted text from the pull request: cap its length, strip
mentions and links, and take the pull request number, head SHA and changed
files from the API, never from the artifact.

Before acting, re-read the pull request and do nothing if its head moved past
the run's SHA (a newer run will decide). Edit or replace the bot's previous
review instead of stacking new ones.

**Identity.** Approve with a GitHub App installed on the repository (pull
requests: write; members: read for the QA team check), using a pinned
`actions/create-github-app-token` and the App's client ID and private key as
secrets. The repository owner creates the App; guide them step by step. The
alternative is the built-in token with the repository setting "Allow GitHub
Actions to create and approve pull requests". Warn the owner before they choose
it: with that setting on, a workflow edited in any branch can approve its own
pull request as `github-actions[bot]`, so that identity's approvals must not
count toward required reviews. Whether the App's approval counts is the
owner's choice in branch protection.

### 4. `qa-review-trigger`: re-decide on reviews

A workflow on `pull_request_review` with no permissions and no steps that
touch the code, listed in `qa-approval`'s `workflow_run` triggers, so a QA's
approving review re-runs the authorship decision (`qa-authorship.md`).

### Secrets stay out of pull request code

On `pull_request` events the workflow file itself comes from the pull request,
so anything a `qa-gate` job can reach, the pull request can reach. Never give
`qa-gate` a secret or a write token. The App key and any board credential live
only in `workflow_run` workflows, which run the default branch's file and never
check out or run the pull request's code. Check out with
`persist-credentials: false`.

## Making sure it works

On a real pull request, show the QA:

1. The gate passing, its comment, the bot's approval and the Allure report.
2. A commit that breaks one scenario on purpose (on a throwaway branch): the
   gate fails, the comment names the scenario and error, the bot requests
   changes.
3. A pull request with no ticket: the bot does not approve.

Then delete the throwaway branch. Never leave the deliberate failure on a
branch that could merge.
