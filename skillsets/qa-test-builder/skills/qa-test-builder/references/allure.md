# Allure

Every QA run produces an Allure report: locally for the QA, and in CI as a run
artifact.

## Set up

In the `package.json` that owns Playwright, add as dev dependencies, pinned to
exact versions:

- `allure-playwright`: the Playwright reporter;
- `allure-js-commons`: the API for links and labels inside tests;
- `allure`: the report generator (Allure 3, a Node package, no Java needed).

Add the reporter to the Playwright config next to the existing reporters:

```ts
reporter: [
  ["list"],
  ["json", { outputFile: "qa-reports/results.json" }],
  ["allure-playwright", {
    resultsDir: "allure-results",
    links: {
      issue: { urlTemplate: "https://example.atlassian.net/browse/%s", nameTemplate: "%s" },
      tms: { urlTemplate: "https://github.com/owner/repo/search?q=%s", nameTemplate: "%s" },
    },
    environmentInfo: { app: "owner/repo", node: process.version },
  }],
],
```

Add a report config file (`allurerc.mjs`) with the report name and the results
and output folders, so `npx allure generate` needs no flags.

If the repository already uses Allure 2 (Java-based CLI), keep it and only add
the Playwright reporter.

## What the report must show

- Each test with its scenario ID as a tag and test-management link, and its
  ticket as an issue link.
- Grouping by ticket: add `allure.epic(<epic or project>)`,
  `allure.feature(<ticket title>)` and `allure.story(<scenario title>)` in the
  helper, so the report's Behaviors tab reads as tickets and scenarios.
- Steps for multi-step scenarios (`await test.step("Open the order summary", ...)`),
  so a failure points at the step.
- Screenshots and traces on failure (`use: { screenshot: "only-on-failure",
  trace: "retain-on-failure" }`). Allure attaches them.
- History between runs is optional. In CI it needs the previous report's
  history folder; keep it only if the QA wants trends.

## Where the report goes

- Locally: `npm run qa:report` opens it.
- CI: upload `allure-report/` as a run artifact (14 days is a good default) and
  link it from the pull request comment.
- Do not publish it to GitHub Pages, a public bucket or any public URL: it
  contains screenshots and data from the app. If the organisation already runs
  a private Allure server or Allure TestOps, upload there instead, with its
  token as a CI secret.
