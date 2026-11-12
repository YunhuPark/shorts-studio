import { defineConfig } from "@playwright/test";
import base from "./playwright.config";
import { E2E_SERVER, PYTHON } from "./playwright.shared";

// Runs e2e/demo.spec.ts against the real demo/ bundle served in demo mode (no keys, no providers): `npm run test:e2e:demo`.
const API = "http://127.0.0.1:8766";
const WEB = "http://127.0.0.1:3011";

// DEMO_URL=http://127.0.0.1:3100 runs the same tests against an already running demo (the container, a deployed site)
// instead of starting the servers. Raise the demo's rate limit for that run (SHORTS_DEMO_RATE): the tests click a lot.
const external = process.env.DEMO_URL;

export default defineConfig({
  ...base,
  testMatch: "demo.spec.ts",
  testIgnore: undefined,
  use: { ...base.use, baseURL: external ?? base.use?.baseURL },
  webServer: external ? undefined : [
    {
      command: `${PYTHON} ${E2E_SERVER} --port 8766 --demo`,
      url: `${API}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npx next build && npx next start -p 3011",
      url: WEB,
      env: { API_ORIGIN: API, NEXT_DIST_DIR: ".next-e2e" },
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
});
