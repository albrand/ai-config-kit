# Survey the repository

Find out what exists before you build anything. Read; do not install or change
anything in this phase.

## What to look for

| Question | Where to look |
|---|---|
| What is the app? | `README*`, top-level folders, `package.json`, `*.sln`/`*.csproj`, `pyproject.toml`, `go.mod`, `pom.xml`/`build.gradle`, `Dockerfile`, `docker-compose*.yml` |
| Frontend, backend or both? | A web framework (`next`, `react`, `vue`, `angular`, `svelte`) is a frontend. Controllers, routes, an ORM or migrations make a backend. |
| How does it start locally? | `package.json` scripts, `Makefile`, `Procfile`, `launchSettings.json`, `docker-compose*.yml`, `README` "run" sections, the CI deploy workflow |
| What does it need to start? | Environment variables (`.env.example`), database (connection strings, migrations), external services (email, storage, payments, auth providers) |
| Which tests exist? | `playwright.config.*`, `cypress.config.*`, `jest.config.*`, `vitest.config.*`, `*Tests*.csproj`, `pytest.ini`/`conftest.py`, `*_test.go`, `src/test/` |
| Is there a QA layer already? | A QA config (`qa/qa.config.json` or similar), scenario files with IDs, test titles tagged with ticket keys, an Allure config (`allurerc.*`, `allure-results` in `.gitignore`) |
| What CI runs? | `.github/workflows/*`, `.gitlab-ci.yml`, `azure-pipelines.yml`, `bitbucket-pipelines.yml`, `Jenkinsfile`, `.circleci/` |
| What are the repository rules? | `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING*`, `CODEOWNERS`, branch protection (`gh api repos/<owner>/<repo>/branches/main/protection` when you have access) |

Also note the runtime versions the project pins (`.nvmrc`, `engines`,
`global.json`, `.python-version`, `.tool-versions`) so the test layer and CI
use the same ones.

## Classify

- **Ready**: a QA config and scenario files exist and tests are traced to
  scenario IDs. Read the repository's own QA instructions and follow them. Your
  job is scenarios and tests, plus whatever the setup lacks (Allure, a separate
  test repository, board reporting).
- **Partial**: a test runner exists (usually Playwright) without traceability,
  a gate or Allure. Keep every existing test and its config. Add a QA project or
  folder next to them.
- **Other tooling**: tests exist in another framework. Do not convert or delete
  them. QA scenarios get their own Playwright setup. In a repository that is not
  Node-based, put it in a self-contained folder with its own `package.json` and
  lockfile (for example `qa/`) so it does not touch the app's build.
- **None**: nothing to keep. Build from `framework-blueprint.md`.

A repository can mix states, for example a frontend with Playwright and no CI.
Write down each part.

## Things that change the plan

- **No CI at all.** You will add the first workflow. Say so to the QA in plain
  terms: the repository owner has to accept a new automated check.
- **CI is not GitHub Actions.** The blueprint's contracts still apply. Translate
  the workflows to that CI system and say which features differ (for example how
  it exposes the pull request title, or how it stores secrets).
- **The app cannot start without real external services.** Find the switch the
  developers use locally (a fake provider, a sandbox key, a feature setting for
  tests). If none exists, a UI test can mock the network
  (`writing-tests.md`), and an API test needs the service stubbed in-process. If
  that needs a code change, it is a developer task: tell the QA what to ask for,
  and design those scenarios as `awaiting-implementation` or `manual-only` until
  then.
- **A monorepo.** Survey each app separately and keep one QA config per
  deployable app, or one config with a section per app. Ask the QA which apps
  are in scope.

## Report back

Tell the QA in four or five lines: what the app is, how it starts, what tests
and CI exist, the state you classified, and what you will need to build. Then
ask where the tests should live (`SKILL.md`, Phase 1).
