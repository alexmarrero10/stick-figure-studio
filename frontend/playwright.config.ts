import { defineConfig } from "@playwright/test";

// Browser tests: the built UI (vite preview) with a fake backend (e2e/mock.ts). Uses the Edge that
// ships with Windows, so no browser download is needed.
export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:4179",
    channel: "msedge",
    viewport: { width: 1366, height: 860 },
    trace: "retain-on-failure",
  },
  outputDir: "e2e/results",
  webServer: {
    command: "npx vite preview --port 4179 --strictPort --host 127.0.0.1",
    url: "http://127.0.0.1:4179",
    reuseExistingServer: false,
  },
});
