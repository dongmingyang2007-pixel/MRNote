import { defineConfig } from "@playwright/test";

const playwrightPort = process.env.PLAYWRIGHT_PORT || "3100";
const baseURL = process.env.PLAYWRIGHT_BASE_URL || `http://localhost:${playwrightPort}`;
const useExternalServer = process.env.PLAYWRIGHT_EXTERNAL_SERVER === "1";
const configuredWorkers = Number(process.env.PLAYWRIGHT_WORKERS || "3");
const workers = Number.isFinite(configuredWorkers) && configuredWorkers > 0 ? configuredWorkers : 3;

export default defineConfig({
  testDir: "./tests",
  workers,
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  webServer: useExternalServer
    ? undefined
    : {
        command: `npx next dev -p ${playwrightPort} -H localhost`,
        env: {
          ...process.env,
          NEXT_PUBLIC_API_BASE_URL: baseURL,
          INTERNAL_API_BASE_URL: "http://localhost:8000",
        },
        url: baseURL,
        reuseExistingServer: false,
        timeout: 120000,
      },
});
