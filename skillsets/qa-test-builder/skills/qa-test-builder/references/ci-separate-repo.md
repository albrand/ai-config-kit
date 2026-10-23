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

1. **A GitHub App** (recommended): installed on both repositories with contents:
   read, pull requests: write and members: read. Each workflow mints a short
   token with `actions/create-github-app-token`, scoped with `repositories:` to
   the two repositories. The same App can be the approval bot.
2. **A fine-grained personal access token** from a service account, limited to
   the two repositories with contents: read. Simpler, but tied to a person's
   account and it expires.

Store the App's client ID and private key (or the token) as secrets in both
repositories. Guide the owner through each screen. You never see or type the
secret.

## App repository: `qa-gate`

Same triggers, jobs and outputs as `ci-same-repo.md`, with these changes:

1. Check out the app pull request (the code under test).
2. Mint the token and check out the tests repository's **main** branch into
   `qa-tests/`. This is the trusted copy: its tools, policy, scenarios and tests
   judge the pull request, and the pull request cannot change them.
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
2. Mint the token and check out the app at the ref to test: the app's main
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
  the QA wants it; it needs the App token with actions: write.

## Making sure it works

Prove both directions on real pull requests, with the same three checks as
`ci-same-repo.md` (pass, deliberate failure, no ticket), and one more: a
change to a test merged in the tests repository is picked up by the next app
pull request's run. Record the run links for the final report.
