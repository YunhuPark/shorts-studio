import { defineConfig, devices } from "@playwright/test";
import { E2E_SERVER, PYTHON } from "./playwright.shared";

// End-to-end tests run against a private API with fake providers (tests/e2e_server.py) and a production build
// of the frontend in its own folder, so they never touch real keys, paid services, or a dev server you have open.
const API_PORT = 8766;
const WEB_PORT = 3011;
const API = `http://127.0.0.1:${API_PORT}`;

export default defineConfig({
  testDir: "./e2e",
  testIgnore: "demo.spec.ts", // the demo bundle has its own config: playwright.demo.config.ts
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${WEB_PORT}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${PYTHON} ${E2E_SERVER} --port ${API_PORT}`,
      url: `${API}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npx next build && npx next start -p ${WEB_PORT}`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: { API_ORIGIN: API, NEXT_DIST_DIR: ".next-e2e" },
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
});
