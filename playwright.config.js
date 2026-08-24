// @ts-check
const { defineConfig, devices } = require('@playwright/test');

/**
 * End-to-end config for the browser-interaction layer of the test suite.
 *
 * These specs drive the real React app in a real Chromium. They deliberately do
 * NOT require the Flask API or PostgreSQL: everything asserted here is
 * client-side map/selection behaviour, which is exactly the layer jsdom cannot
 * reach and the Python tests never see. The app degrades to "no forecast
 * overlay" without the API, and the map still handles input normally.
 *
 * Run:  npm run test:e2e          (headless)
 *       npm run test:e2e:headed   (watch it happen)
 */
module.exports = defineConfig({
  testDir: './e2e',
  // The map has to settle (tiles, Leaflet init) before most specs can act.
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],

  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000',
    viewport: { width: 1600, height: 1000 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    navigationTimeout: 60_000,
  },

  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],

  // Reuses an already-running `npm start` locally; boots one in CI.
  webServer: {
    command: 'BROWSER=none npm start',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    stdout: 'ignore',
    stderr: 'pipe',
  },
});
