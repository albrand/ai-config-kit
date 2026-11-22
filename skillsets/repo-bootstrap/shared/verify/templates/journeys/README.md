# Journeys

A journey is a person using the product: a persona starts where they really start, moves through
visible controls (links, buttons, forms, keyboard), reaches an outcome they care about, and the
journey checks what they would see. It runs against the real frontend and the real backend.

Files to copy into the repo (for example `journeys/`):

- [journey.fixture.ts](journey.fixture.ts): fails the journey when it answers the app's own
  requests with `route.fulfill`, when the backend returns 5xx or an API call returns 4xx, when an
  own-origin request fails, or when the page throws. List expected errors in `allowedErrors`.
- [personas.ts](personas.ts) and [auth.setup.ts](auth.setup.ts): seeded test accounts, signed in
  once through the real login screen. Credentials come from env, never from the repo.
- [example.journey.ts](example.journey.ts): the shape of a journey.
- [playwright.journeys.config.ts](playwright.journeys.config.ts): desktop and phone, no retries.

## Writing one

1. Name the persona, the entry point and the outcome in the test title.
2. Use `getByRole`, `getByLabel` and `getByText`, the way a person finds things. Avoid CSS
   selectors and test IDs unless nothing visible identifies the control.
3. Assert what the person sees, then prove the backend kept it: reload, leave and come back, or
   look at it as a second persona.
4. Seed the data the journey needs before it runs (a seed script or API call in `globalSetup`),
   with unique names per run. Never answer the app's own API inside a journey.
5. Faking third parties is fine and often necessary: block analytics, and stop at the payment
   provider's page instead of paying.
6. Cover the unhappy path a person hits: wrong password, empty state, permission denied, slow
   network (`page.route` with a delay that then calls `route.continue()`).
7. Tag the handful that must pass after every deploy with `@smoke`.

A flaky journey is a defect. Find the race (usually a missing wait for a visible result), do not
add retries.

## api

A service with no UI still gets journeys: a client drives the running service over HTTP, in the
order a real client would, against `BASE_URL` and a real database.

```ts
// api.journey.test.ts (node:test, Node 20+)
import test from 'node:test';
import assert from 'node:assert/strict';
const base = process.env.BASE_URL;

test('a client registers, creates an order and reads it back', async () => {
  const user = await (await fetch(`${base}/users`, { method: 'POST', body: JSON.stringify({ name: `j-${Date.now()}` }),
    headers: { 'content-type': 'application/json' } })).json();
  const order = await fetch(`${base}/orders`, { method: 'POST', body: JSON.stringify({ userId: user.id, sku: 'A1' }),
    headers: { 'content-type': 'application/json' } });
  assert.equal(order.status, 201);
  const back = await (await fetch(`${base}/orders/${(await order.json()).id}`)).json();
  assert.equal(back.userId, user.id);
});
```

Python services do the same with `pytest` and `httpx` against `BASE_URL`.
