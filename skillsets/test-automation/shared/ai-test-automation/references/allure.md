# Allure by runner

All examples target the application repository. Install the runner adapter there, not in `templates/qa-kit`; the kit itself remains Node-built-ins-only. Pin versions in the app lockfile. Every automated scenario must emit a stable Allure label named `scenario_id` with value `QAS-<work-item>-<nn>`. Result parsing reads runner-native files as the authority; a rendered report or test title is not proof that a test executed.

| Runner | Install | Results directory | Parser behavior |
|---|---|---|---|
| Playwright | `npm install --save-dev allure allure-playwright` | `allure-results/` plus `test-results/` screenshots | `lib/results/parsers.mjs` reads Playwright JSON annotations and status, then joins Allure result labels for attachments |
| Vitest | `npm install --save-dev allure @vitest/runner allure-vitest` | `allure-results/` | Allure result JSON `labels[]` |
| Jest | `npm install --save-dev allure allure-jest` | `allure-results/` | Allure result JSON `labels[]` |
| pytest | `python -m pip install allure-pytest` (and install Allure Report 3 CLI for generation) | `allure-results/` | Allure result JSON `labels[]` |
| xUnit | `dotnet add package Allure.Xunit`; report project: `npm install --save-dev allure` | `allure-results/` | Allure result JSON `labels[]` |
| NUnit | `dotnet add package Allure.NUnit`; report project: `npm install --save-dev allure` | `allure-results/` | Allure result JSON `labels[]` |
| JUnit 5 | Maven: add `io.qameta.allure:allure-junit5` test dependency; Gradle: `testImplementation("io.qameta.allure:allure-junit5:<pinned-version>")`; report project: `npm install --save-dev allure` | `allure-results/` | JUnit XML names/status plus Allure result labels when produced |

Check the runner adapter's current official setup guide before copying a version-specific setting. The exact package versions are intentionally selected and locked by the application owner.

## Playwright

```js
// playwright.config.ts
export default defineConfig({ reporter: [['list'], ['allure-playwright', { resultsDir: 'allure-results' }]] });
```

```ts
import { test, expect } from '@playwright/test';
import * as allure from 'allure-js-commons';
test('QAS-WI-123-01 checkout rejects an expired coupon', async ({ page }, testInfo) => {
  await allure.label('scenario_id', 'QAS-WI-123-01');
  await page.goto('/checkout');
  // ... assertions ...
  const path = testInfo.outputPath('scenario.png');
  await page.screenshot({ path, fullPage: true });
  await testInfo.attach('scenario screenshot', { path, contentType: 'image/png' });
});
```

Run `npx playwright test --reporter=allure-playwright`; configure Playwright JSON output as a second reporter (for example `['json',{outputFile:'qa-results/playwright.json'}]`) for the built-in parser. Upload `allure-results/`, JSON and screenshots as one immutable CI artifact. Screenshots are required for every executed browser scenario; missing attachment confirmation blocks.

## Vitest

```ts
// vitest.config.ts
import { defineConfig } from 'vitest/config';
export default defineConfig({ test: { setupFiles: ['allure-vitest/setup'], reporters: ['default', ['allure-vitest/reporter', { resultsDir: 'allure-results' }]] } });
```

Import `allure` from `allure-js-commons` and call `await allure.label('scenario_id', id)` inside each test. For screenshot evidence in a browser test, capture with the browser fixture and call the adapter's attachment API (`attachment(name,{contentType:'image/png',source:Buffer})`) before the test completes. Also emit JUnit XML with a reporter option if CI needs `parseJunitXml`; parser IDs are extracted from testcase names when no Allure result exists.

## Jest

```js
// jest.config.cjs
module.exports = { reporters: ['default', ['allure-jest', { resultsDir: 'allure-results' }]] };
```

Import the Allure Jest runtime and call its `label('scenario_id', id)` API in the test body; keep the adapter's generated JSON in `allure-results/`. Attach browser screenshots via the adapter attachment API. Configure JUnit output if you want `parseJunitXml` as a second evidence source. The gate requires a result with the stable ID and an executed outcome; label-only metadata in source does not pass.

## pytest

```ini
# pytest.ini
[pytest]
addopts = --alluredir=allure-results --junitxml=qa-results/junit.xml
```

```python
import allure
@allure.label("scenario_id", "QAS-WI-123-02")
def test_coupon_rejected(page):
    expect(page.get_by_role("alert")).to_have_text("Coupon expired.", use_inner_text=True)
    allure.attach(page.screenshot(full_page=True), name="scenario screenshot", attachment_type=allure.attachment_type.PNG)
```

A screenshot is evidence, never an assertion.

The runner emits `allure-results/*-result.json`; the starter parser extracts the custom label from `labels`. Keep JUnit XML for cross-checking discovery and execution.

## xUnit and NUnit

Add the adapter to the test project (`Allure.Xunit` or `Allure.NUnit`) and configure the Allure CLI results directory as `allure-results`. Set a dynamic label `scenario_id` from the test method using the adapter's runtime API; do not rely solely on a display name. For UI/browser scenarios, capture the screenshot from the browser test and attach PNG bytes with the adapter's attachment API. Generate TRX with `dotnet test --logger trx --results-directory qa-results`; `parseTrx` extracts test name, outcome and executed status. Retain Allure result JSON to retain labels and attachments.

## JUnit 5

Configure `io.qameta.allure:allure-junit5` in the Gradle/Maven test runtime and set `allure.results.directory=allure-results`. Use `@LabelAnnotation(name="scenario_id", value="QAS-WI-123-03")` or the supported Allure lifecycle API to assign the label. Attach screenshots with `Allure.addAttachment("scenario screenshot", "image/png", inputStream, ".png")`. `parseJunitXml` extracts IDs from an agreed stable testcase name; Allure JSON is preferred because it carries labels and attachment references.

## Allure 3 single-file report

Use a pinned Allure 3 CLI version supported by your environment. Example `allurerc.mjs` configuration (confirm exact option names against that pinned CLI before adopting):

```js
import { defineConfig } from 'allure';

export default defineConfig({
  name: 'QA test report',
  output: './allure-report',
  historyPath: './allure-history/history.jsonl',
  plugins: {
    awesome: {
      options: {
        reportName: 'QA test report',
        singleFile: true,
        reportLanguage: 'en',
        groupBy: ['sprint', 'feature', 'scenario_id'],
        open: false
      }
    }
  }
});
```

The test adapter writes to `allure-results/`; Allure Report 3 reads those result files as the positional input to `allure generate` / `allure awesome`. For non-Node runner projects, use a static `allurerc.json` equivalent or keep the dynamic config in the QA/reporting Node project.

Store sprint/feature as Allure labels and `scenario_id` as the stable scenario label. Generate with the pinned CLI's report command, producing one portable HTML file. Publish it and raw result files as an access-controlled CI artifact with retention matching the evidence policy. Wait for artifact upload success and capture its immutable URL before adding the ticket link. The board report comment includes item ID, candidate commit, content-hash marker, verdict summary and artifact URL; a failed board write leaves the verdict BLOCKED.

Official setup references: [Allure Playwright](https://allurereport.org/docs/playwright/), [Allure Vitest](https://allurereport.org/docs/vitest/), [Allure 3 configuration](https://allurereport.org/docs/v3/configure/), [Allure attachments](https://allurereport.org/docs/attachments/).

### Exact dependency snippets for JVM and .NET

```sh
# In a Node report project used for Node, Python, .NET and Java results
npm install --save-dev allure
# Python runner project
python -m pip install allure-pytest
# .NET runner project
 dotnet add package Allure.Xunit
 dotnet add package Allure.NUnit
```

For Maven/JUnit 5, add this test dependency (pin the version with your dependency management):

```xml
<dependency>
  <groupId>io.qameta.allure</groupId>
  <artifactId>allure-junit5</artifactId>
  <version>${allure.version}</version>
  <scope>test</scope>
</dependency>
```

For Gradle, use `testImplementation("io.qameta.allure:allure-junit5:<pinned-version>")`. For .NET browser tests, attach the screenshot file with the runner adapter's attachment API after capture and also retain a TRX result file under `qa-results/`.

### Jest test-level binding and browser attachment

```js
import * as allure from 'allure-js-commons';

test('QAS-WI-123-04 profile page loads', async () => {
  await allure.label('scenario_id', 'QAS-WI-123-04');
  await expect(page.getByRole('heading')).toHaveText('Profile', { useInnerText: true });
  const png = await browser.screenshot();
  await allure.attachment('scenario screenshot', png, 'image/png');
});
```

A screenshot is evidence, never an assertion.

Confirm the installed Jest adapter exposes the same runtime API; if its version uses a different runtime entry point, keep the equivalent label and binary attachment calls and assert the resulting JSON label in a parser fixture. The parser consumes each `allure-results/*-result.json`; it does not infer the ID from the test title.

### xUnit / NUnit test-level binding

```csharp
// Adapter attribute names are version-specific; dynamic labels keep generated IDs out of source annotations.
AllureApi.AddLabel("scenario_id", "QAS-WI-123-05");
var bytes = await page.ScreenshotAsync();
AllureApi.AddAttachment("scenario screenshot", "image/png", bytes);
```

Keep the test case discoverable by the selected xUnit/NUnit adapter. Use `dotnet test --logger trx --results-directory qa-results` and parse the TRX outcome; read Allure `labels` for the authoritative scenario binding. Check the selected Allure .NET package's runtime namespace at upgrade time.

### Runner result parser contract

`lib/results/parsers.mjs` exports `parseJunitXml(xml)`, `parseTrx(xml)`, `parsePlaywrightJson(data)`, and `parseAllureResults(rows)`. Each returns `{ scenario_id, status, executed, screenshot }`. JUnit extracts `QAS-…` from `<testcase name>`, TRX from `UnitTestResult.testName`, Playwright from annotation type `scenario_id`, and Allure from `labels[{name:"scenario_id",value}]`; skipped/NotExecuted status is never executed evidence. Preserve the raw source artifact so each parser result can be traced to a runner output.
