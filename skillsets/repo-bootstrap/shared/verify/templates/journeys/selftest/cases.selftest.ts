// Each case states what the fixture must do. Run with the JSON reporter and compare outcomes.
import { test, expect } from './journey.fixture';

test('real backend: passes', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('real')).toBeVisible();
});

test('fakes own API: must fail', async ({ page }) => {
  await page.route('**/api/data', (route) => route.fulfill({ status: 200, body: '{"items":["fake"]}' }));
  await page.goto('/');
  await expect(page.getByText('fake')).toBeVisible({ timeout: 3000 });
});

test('backend 500: must fail', async ({ page }) => {
  await page.goto('/boom');
  await expect(page.getByRole('heading', { name: 'Boom' })).toBeVisible();
  await page.waitForTimeout(500);
});

test('third party blocked: passes', async ({ page }) => {
  await page.route('https://analytics.example.invalid/**', (route) => route.abort());
  await page.goto('/third');
  await expect(page.getByRole('heading', { name: 'Third' })).toBeVisible();
});

test('third party faked: passes', async ({ page }) => {
  await page.route('https://analytics.example.invalid/**', (route) => route.fulfill({ body: '' }));
  await page.goto('/third');
  await expect(page.getByRole('heading', { name: 'Third' })).toBeVisible();
});

test.describe('expected error allowed', () => {
  test.use({ allowedErrors: [/\/api\/boom$/] });
  test('backend 500 listed in allowedErrors: passes', async ({ page }) => {
    await page.goto('/boom');
    await expect(page.getByRole('heading', { name: 'Boom' })).toBeVisible();
    await page.waitForTimeout(500);
  });
});
