# CI when the tests live in a separate repository

Two repositories: the **app repository** (the code) and the **tests repository**
(the QA layer from `framework-blueprint.md`, the scenarios and the Playwright
tests). Both directions must work:

- a pull request on the **app** runs the tests of the tickets it names, from the
  tests repository's main branch, against the app built from the pull request;
- a pull request on the **tests** repository (QA adding or changing tests) runs
  those tests against the app's main branch, or against the branch the scenario
  is `awaiting`.

## Access between the repositories

The built-in CI token can only read its own repository. Pick one, with the
repository owner:

1. **A reader GitHub App** (recommended): installed on both repositories with
   contents: read only. Workflows mint a short token with
   `actions/create-github-app-token`, narrowed with its `repositories:` input
   to the one repository they need to read and its permission inputs to
   contents: read.
2. **A fine-grained personal access token** from a service account, limited to
   the two repositories with contents: read. Simpler, but tied to a person's
   account and it expires.

The reader must be a different identity from the approval App, so code that
somehow obtained the reader token still cannot approve anything.

Store the client ID and private key (or the token) as secrets in both
repositories. Guide the owner through each screen. You never see or type the
secret.

### Keep the reader token away from code under test

A job that runs pull request code can read every secret and token that job
holds. So fetch the other repository in its own job, before any pull request
code runs:

1. Job `fetch`: mint the reader token, check out the other repository at the
   ref you need with `persist-credentials: false`, and upload it as an artifact
   (exclude `.git`). This job never checks out the pull request.
2. Job `qa-gate`, `needs: fetch`: no secrets; downloads that artifact and runs
   everything else.

On `pull_request` events the workflow file comes from the pull request, so a
branch could rewrite `fetch` to print the token. That is why the reader is
contents: read on one repository only and expires within the hour, and why it
cannot approve. If that exposure is too much for the owner, run the whole gate
from `workflow_run` instead and accept the slower feedback.

## App repository: `qa-gate`

Same triggers, jobs and outputs as `ci-same-repo.md`, with these changes:

1. `fetch` job: the tests repository's **main** branch, as an artifact. This is
   the trusted copy: its tools, policy, scenarios and tests judge the pull
   request, and the pull request cannot change them.
2. `qa-gate` job: check out the app pull request (the code under test) and
   unpack the tests artifact into `qa-tests/`.
3. Build and start the app from the pull request (the `webServer` command in
   the tests repository's config, pointed at the app checkout with an
   environment variable such as `APP_DIR`).
4. `check`, `plan` (from the app pull request's title, branch and body), `run`,
   `gate`, `report`, in `qa-tests/`.
5. The comment and approval jobs act on the app pull request, exactly as in
   `ci-same-repo.md`.

A developer who wants to change a test opens a pull request on the tests
repository. The app pull request picks it up once it merges there.

## Tests repository: `qa-gate`

Triggered by pull requests on the tests repository.

1. Check out the tests pull request. Trusted tools and policy come from the
   tests repository's main branch, as in `ci-same-repo.md`.
2. `fetch` job: the app at the ref to test, as an artifact: the app's main
   branch by default; for scenarios marked `awaiting` a branch or pull request,
   that ref, so QA can prove a test against a feature that is not merged yet.
3. Start the app and run the plan: the tickets named in the tests pull request,
   plus the baseline.
4. Gate, report, comment and approval on the tests pull request, plus the
   authorship check (`qa-authorship.md`).

## Keeping the two in step

- When the app's main branch changes behaviour the tests cover, the next app
  pull request fails the gate: that is the signal, not a fault of the wiring.
- Optional: a nightly or post-merge run on the app's main branch with the full
  regression set, reported the same way, so drift is caught even without a
  pull request.
- Optional: a `repository_dispatch` from the tests repository's main branch
  that re-runs the gate on open app pull requests after tests change. Only if
  the QA wants it; it needs a separate token with actions: write on the app
  repository, used only in a workflow that runs on the tests repository's main
  branch.

## Making sure it works

Prove both directions on real pull requests, with the same three checks as
`ci-same-repo.md` (pass, deliberate failure, no ticket), and one more: a
change to a test merged in the tests repository is picked up by the next app
pull request's run. Record the run links for the final report.
