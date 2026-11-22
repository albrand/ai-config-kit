// A journey: one persona, one outcome they care about, every step through visible controls.
// Rename to <outcome>.journey.ts. Tag the few journeys that must pass after every deploy with @smoke.
import { test, expect } from './journey.fixture';
import { storageStatePath } from './personas';

test.use({ storageState: storageStatePath('member') });

test('a member creates a note and finds it again after coming back @smoke', async ({ page }) => {
  const title = `Journey note ${Date.now()}`;

  await test.step('opens the notes screen from the main navigation', async () => {
    await page.goto('/');
    await page.getByRole('navigation').getByRole('link', { name: /notes/i }).click();
    await expect(page.getByRole('heading', { name: /notes/i })).toBeVisible();
  });

  await test.step('creates a note', async () => {
    await page.getByRole('button', { name: /new note/i }).click();
    await page.getByLabel(/title/i).fill(title);
    await page.getByRole('button', { name: /save/i }).click();
    await expect(page.getByText(title)).toBeVisible();
  });

  await test.step('leaves, comes back, and the note is still there (the backend stored it)', async () => {
    await page.goto('/');
    await page.reload();
    await page.getByRole('navigation').getByRole('link', { name: /notes/i }).click();
    await expect(page.getByText(title)).toBeVisible();
  });
});
