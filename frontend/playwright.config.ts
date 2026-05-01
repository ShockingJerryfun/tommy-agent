import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "retain-on-failure",
    actionTimeout: 5_000,
    navigationTimeout: 15_000,
  },
  webServer: {
    command:
      "PORT=3100 NEXT_PUBLIC_E2E=1 AGENT_API_URL=http://127.0.0.1:3100/e2e-backend npm run dev",
    url: "http://127.0.0.1:3100",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    stdout: "pipe",
    stderr: "pipe",
  },
  projects: [
    {
      name: "desktop-chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } },
    },
    { name: "mobile-iphone-12", use: { ...devices["iPhone 12"] } },
  ],
});
