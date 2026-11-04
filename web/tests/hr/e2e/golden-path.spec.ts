/**
 * HR 金路径 E2E（批 C4）：登录 → 花名册 → 岗位一条 CRUD → 退出
 *
 * 运行环境：运行态前后端（testbed 自举或本机拉起）+ 主仓 web/vue 工具链。
 *
 * 环境变量：
 * - E2E_BASE_URL  前端服务地址（默认 http://localhost:5173）
 * - 种子账号 admin/admin123（testbed bootstrap 的 seed 口径）
 *
 * 运行：cd web/vue && E2E_BASE_URL=... \
 *       pnpm exec playwright test --config tests/hr/e2e/playwright.config.ts
 */
import { expect, test, userLoginViaAPI } from "./fixtures";

test.describe("HR 金路径", () => {
  test.beforeEach(async ({ page, request }) => {
    await userLoginViaAPI(page, request, "admin", "admin123");
  });

  test("花名册页加载：统计卡与建档入口可见", async ({ page }) => {
    await page.goto("/hr/employees");
    // 统计卡（在编/试用/本月新入职/离职率）+ 入职建档按钮
    await expect(page.getByTestId("employee-stat-cards")).toBeVisible({
      timeout: 20000,
    });
    await expect(page.getByTestId("open-create-modal")).toBeVisible();
  });

  test("岗位一条 CRUD：新建 → 列表可见 → 删除", async ({ page }) => {
    const code = `e2e_${Date.now()}`;
    const name = `E2E 岗位 ${code}`;

    await page.goto("/hr/positions");
    await expect(page.getByTestId("open-create-position")).toBeVisible({
      timeout: 20000,
    });

    // 新建
    await page.getByTestId("open-create-position").click();
    const dialog = page.getByTestId("position-form-dialog");
    await expect(dialog).toBeVisible({ timeout: 10000 });
    await page.getByTestId("position-code-input").locator("input").fill(code);
    await page.getByTestId("position-name-input").locator("input").fill(name);
    await page.getByTestId("position-submit").click();
    await expect(dialog).not.toBeVisible({ timeout: 15000 });

    // 列表可见（关键字检索命中新建岗位）
    await page.getByTestId("position-keyword-input").locator("input").fill(code);
    await page.getByTestId("position-search").click();
    const row = page.getByRole("row", { name: new RegExp(code) });
    await expect(row.first()).toBeVisible({ timeout: 15000 });

    // 删除：行操作下拉（MoreHorizontal）→ 删除 → MessageBox 确认
    await row.first().locator("button").last().click();
    await page.getByRole("menuitem", { name: "删除" }).click();
    await page.getByRole("button", { name: "确认" }).click();
    await expect(row.first()).not.toBeVisible({ timeout: 15000 });
  });

  test("退出登录：回登录页", async ({ page }) => {
    await page.goto("/hr/employees");
    await expect(page.getByTestId("employee-stat-cards")).toBeVisible({
      timeout: 20000,
    });

    // 头部用户面板（AdminLayout header 最后一个按钮）→ 退出登录
    await page.locator("header button").last().click();
    await page.getByRole("menuitem", { name: "退出登录" }).click();
    await expect(page).toHaveURL(/\/login/, { timeout: 15000 });
  });
});
