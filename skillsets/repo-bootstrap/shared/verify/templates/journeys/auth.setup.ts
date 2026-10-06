// Signs each persona in through the real login screen once, and saves the session for the journeys.
// Change the labels to match your login form.
import { test as setup, expect } from '@playwright/test';
import { PERSONAS, storageStatePath } from './personas';

for (const persona of PERSONAS.filter((p) => p.emailEnv)) {
  setup(`sign in as ${persona.name}`, async ({ page }) => {
    const email = process.env[persona.emailEnv];
    const password = process.env[persona.passwordEnv];
    if (!email || !password) {
      throw new Error(`${persona.emailEnv} and ${persona.passwordEnv} must be set; a journey that skips proves nothing`);
    }
    await page.goto(persona.entry);
    await page.getByLabel(/e-?mail/i).fill(email);
    await page.getByLabel(/password|senha/i).fill(password);
    await page.getByRole('button', { name: /sign in|log in|entrar/i }).click();
    await expect(page).not.toHaveURL(/login/);
    await page.context().storageState({ path: storageStatePath(persona.name) });
  });
}
