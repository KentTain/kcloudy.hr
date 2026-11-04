import { describe, expect, it } from "vitest";

/**
 * hr 模块编译冒烟：eager glob 强制编译 pages/components/api 全树，
 * 捕获断链导入/缺失依赖（本环境 vue-tsc/build 不可用，vitest 为唯一编译验证面）。
 */

const pageModules = import.meta.glob("@/hr/pages/**/*.vue", { eager: true });
const apiModules = import.meta.glob("@/hr/api/**/*.ts", { eager: true });
const typeModules = import.meta.glob("@/hr/types/**/*.ts", { eager: true });

describe("hr 编译冒烟", () => {
  it("pages 全树可编译（无断链导入）", () => {
    const loaded = Object.keys(pageModules);
    expect(loaded.length).toBeGreaterThanOrEqual(2); // HrModuleLayout + HrPlaceholderPage
  });

  it("api/types 全树可编译", () => {
    expect(Object.keys(apiModules).length).toBeGreaterThanOrEqual(1);
    expect(Object.keys(typeModules).length).toBeGreaterThanOrEqual(1);
  });

  it("模块入口与路由表可加载", async () => {
    const { hrRoutes } = await import("@/hr/router");
    expect(hrRoutes[0].children?.length).toBe(20);
  });
});
