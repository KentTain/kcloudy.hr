/**
 * HR 子仓 e2e 独立配置（批 C4）。
 *
 * 为什么不用主仓 web/vue/playwright.config.ts：主仓 testDir=web/vue/tests，
 * 经目录 symlink（tests/hr）呈现的用例文件真实路径在 testDir 之外，
 * playwright 收集器不跟随目录 symlink，一律 0 用例。本配置直接以本目录为
 * testDir，主仓与 testbed 均可运行：
 *
 *   cd web/vue && E2E_BASE_URL=http://127.0.0.1:15173 \
 *     pnpm exec playwright test --config tests/hr/e2e/playwright.config.ts
 *
 * （testDir 相对配置文件解析，走 symlink 路径调用即可命中真实文件）
 */
import os from "node:os";
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "**/*.spec.ts",
  outputDir: "../../test-results/hr-e2e",
  fullyParallel: true,
  retries: process.env.CI ? 2 : 1,
  workers: process.env.E2E_WORKERS
    ? parseInt(process.env.E2E_WORKERS, 10)
    : Math.min(2, Math.floor(os.cpus().length / 2)),
  reporter: [["line"]],
  timeout: 60000,
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:5173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "off",
    headless: true,
    ignoreHTTPSErrors: true,
    actionTimeout: 10000,
    navigationTimeout: 30000,
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: {
          // 对齐主仓 playwright.config.ts 的内存约束参数
          args: [
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-setuid-sandbox",
            "--no-sandbox",
            "--disable-extensions",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-component-update",
            "--no-first-run",
            "--disable-sync",
            "--disable-background-networking",
            "--js-flags=--max-old-space-size=512",
            "--memory-pressure-off",
            "--max_old_space_size=512",
          ],
        },
      },
    },
  ],
});
