// Run: BASE_URL=http://localhost:3000 npx playwright test -c playwright.journeys.config.ts
// verify config: "journeys": {"run": "npx playwright test -c playwright.journeys.config.ts",
//   "start": "npm run start", "ready_url": "http://localhost:3000", "env": ["JOURNEY_MEMBER_EMAIL", ...]}
// or, against a preview: "base_url": "<command that prints the preview URL for this commit>".
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './journeys',
  testMatch: /.*\.(journey|setup)\.ts/,
  fullyParallel: true,
  // No retries: a journey that passes on the second try has a bug, in the app or in the journey.
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.BASE_URL ?? 'http://localhost:3000',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    { name: 'desktop', use: { ...devices['Desktop Chrome'] }, dependencies: ['setup'], testMatch: /.*\.journey\.ts/ },
    { name: 'phone', use: { ...devices['Pixel 7'] }, dependencies: ['setup'], testMatch: /.*\.journey\.ts/ },
  ],
});
