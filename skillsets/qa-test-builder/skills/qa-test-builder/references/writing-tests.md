# Write the tests

The scenario is the specification. Do not change its expectations to fit the
app. If a scenario is wrong or cannot be tested at its layer, go back to the QA.

## Traceability

Every QA test carries exactly one scenario ID and its ticket key as Playwright
tags, and the same as Allure links, so a reader can go from the report to the
ticket and from the ticket to the test:

```ts
import { test, expect } from "@playwright/test";
import * as allure from "allure-js-commons";

test(
  "vendor dialog shows the street address with a map below it",
  { tag: ["@QAS-7K2M9P", "@PROJ-123"] },
  async ({ page }) => {
    await allure.issue("PROJ-123", "https://example.atlassian.net/browse/PROJ-123");
    await allure.tms("QAS-7K2M9P");
    // ...
  },
);
```

Put this in a small helper (`qaCase("QAS-7K2M9P")`) that reads the scenario
file and returns the tags and links, so tests cannot drift from the scenarios.
A scenario may need several tests; tag each one with the same ID.

## UI tests against a mocked backend (`ui-mocked`)

- Route every call the screen makes with `page.route()`, from a fixture module
  per area (`support/<area>-api.ts`) that builds realistic, synthetic data.
- Make unhandled API calls fail the test or answer empty and get recorded, so a
  missing mock is visible instead of reaching a real server.
- Locate elements as a user would: role and accessible name, label, visible
  text. Use a `data-testid` only where the app already has one. Never use CSS
  structure or generated class names.
- Assert what the user sees: text, visibility, enabled or disabled, the URL,
  the request the app sent (for actions). Every `expected` line gets an assertion.
- No fixed waits. Use Playwright's auto-waiting assertions (`toBeVisible`,
  `toHaveText`, `toHaveURL`) and `waitForResponse` for network.

## API tests (`api`)

QA tests for a backend use Playwright's `request` fixture against the API that
the config's `webServer` starts:

```ts
test("rejects a work order without a vendor", { tag: ["@QAS-2B8QXN", "@PROJ-140"] }, async ({ request }) => {
  const login = await request.post("/api/auth/login", { data: { email: testUsers.admin.email, password: testUsers.admin.password } });
  expect(login.ok()).toBeTruthy();
  const { token } = await login.json();

  const res = await request.post("/api/work-orders", {
    headers: { authorization: `Bearer ${token}` },
    data: { title: "Leaking pipe", vendorId: null },
  });

  expect(res.status()).toBe(400);
  expect(await res.json()).toMatchObject({ errors: { vendorId: expect.anything() } });
});
```

- Put sign-in in a fixture (`support/auth.ts`) that logs in once per role and
  hands the test an authenticated `request` context.
- Create the data each test needs through the API (or a seed endpoint the app
  exposes for tests), and use unique values so tests do not collide.
- Assert the contract the frontend depends on: status code, the fields it
  reads, error shapes. Also assert the effect: after a create, read it back.
- Cover the rejections: missing and invalid fields, the wrong role, another
  tenant's record, the limit and one past it.

## UI tests against a real backend (`ui-e2e`)

Use only when the scenario's point is the integration. Sign in through the UI
once and reuse the stored state. Create data through the API, not by clicking
through setup screens. Clean up what you created.

## Prove each test can fail

After the test passes:

1. Break it on purpose: invert one key assertion, or change the behaviour it
   checks (comment out the line in the app that does it, or change the mocked
   data so the expected value is absent).
2. Run it and confirm it fails with a message that names the broken behaviour.
3. Restore the change. Run it again green.

Tell the QA what you broke and what the failure said. A test that stays green
when the behaviour is gone is not a test.

## When the run fails

| Failure | What it means | What you do |
|---|---|---|
| The app does the wrong thing | A product defect | Report it to the QA with the evidence. Leave the test asserting the correct behaviour. The scenario stays failing until the app is fixed. |
| The feature does not exist yet | Not implemented | Mark the scenario `awaiting-implementation` with the branch or pull request. |
| A locator or mock is wrong | A test defect | Fix the test. Do not loosen the assertion. |
| It passes sometimes | Flaky | Find the race (missing wait on a response, shared data, animation) and fix it. Never add retries or sleeps to hide it. |

## After the tests pass

Set each scenario's `binding` (`status: "draft"`, `file`), set `approvedBy` to
the QA's GitHub login, run `qa:check` and `qa:local`, and check the Allure
report shows every scenario with its ticket link.
