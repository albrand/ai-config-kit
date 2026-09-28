import { defineConfig } from '@playwright/test';

export default defineConfig({
  webServer: {
    command: 'fixture-web-server --port 3000',
    port: 3000,
  },
});
