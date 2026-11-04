/**
 * HR 子仓 e2e 自包含登录辅助（批 C4）。
 *
 * 不复用主仓 tests/tenant/e2e/fixtures（本目录以 testDir 直接收集，跨目录
 * 相对导入在子仓布局下不可达），此内联实现与主仓登录注入语义一致：
 * API 登录 → addInitScript 注入 localStorage（token/tenant_id/refresh_token/
 * token_expires_at，键名对齐 iam auth store）。
 */
import { type APIRequestContext, type Page } from "@playwright/test";

const TOKEN_KEY = "token";
const TENANT_ID_KEY = "tenant_id";
const REFRESH_TOKEN_KEY = "refresh_token";
const TOKEN_EXPIRES_AT_KEY = "token_expires_at";

export async function userLoginViaAPI(
  page: Page,
  request: APIRequestContext,
  account = "admin",
  password = "admin123"
): Promise<void> {
  const loginResponse = await request.post("/api/iam/console/v1/auth/login", {
    data: { account, password },
    timeout: 30000,
  });
  if (!loginResponse.ok()) {
    const errorText = await loginResponse.text();
    throw new Error(`用户登录失败 (HTTP ${loginResponse.status()}): ${errorText}`);
  }

  const loginData = await loginResponse.json();
  const access_token = loginData?.data?.access_token;
  const refresh_token = loginData?.data?.refresh_token;
  const tenant_id = loginData?.data?.tenant_id;
  const expires_in = loginData?.data?.expires_in || 3600;
  if (!access_token) {
    throw new Error(
      `用户登录失败: 响应中未找到 access_token 字段 (响应: ${JSON.stringify(loginData)})`
    );
  }

  const expires_at = Date.now() + expires_in * 1000;
  await page.addInitScript(
    // 键名以字面量内联（addInitScript 仅序列化函数体，模块级常量在浏览器内不可达）
    ({
      access_token,
      refresh_token,
      tenant_id,
      expires_at,
    }) => {
      localStorage.setItem("token", access_token);
      if (refresh_token) {
        localStorage.setItem("refresh_token", refresh_token);
      }
      localStorage.setItem("token_expires_at", String(expires_at));
      if (tenant_id) {
        localStorage.setItem("tenant_id", tenant_id);
      }
    },
    { access_token, refresh_token, tenant_id, expires_at }
  );
}

export { expect, test } from "@playwright/test";
