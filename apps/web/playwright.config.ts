import { defineConfig, devices } from "@playwright/test";

import { WEB_ORIGIN } from "./e2e/ports.mjs";

// Runs against a production build (`npm run test:e2e` builds first) and a mock
// orchestrator; e2e/global-setup.mjs starts both and captures the server log.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  retries: 0,
  reporter: "list",
  globalSetup: "./e2e/global-setup.mjs",
  // Reduced motion by default: the headless browser renders WebGL in software, and an
  // animated globe would compete with the tests for CPU. The globe's own tests opt back in.
  use: { baseURL: WEB_ORIGIN, trace: "off", contextOptions: { reducedMotion: "reduce" } },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
