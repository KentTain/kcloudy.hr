/**
 * hr 模块骨架契约测试（阶段 7.1 + 二期批 A/B）
 *
 * 后端菜单源：server/python/src/hr/module.py get_module_definition()
 * 6 组 20 叶（员工自助/我的假期/团队工作台为 console 层无权限码）；
 * 叶子 path 与前端路由双向一致（段级匹配，本模块无参数路由）。
 */

import { describe, expect, it } from "vitest";

import hrModule from "@/hr";
import { hrRoutes } from "@/hr/router";

describe("hr 模块描述符", () => {
  it("导出 ModuleDescriptor 基本字段", () => {
    expect(hrModule.name).toBe("hr");
    expect(hrModule.version).toBe("0.1.0");
    expect(typeof hrModule.getRoutes).toBe("function");
  });

  it("getRoutes 返回模块路由", () => {
    expect(hrModule.getRoutes()).toBe(hrRoutes);
  });
});

describe("hr 模块路由", () => {
  it("以 hr 根路由挂载（相对路径，setupFramework 挂到 Root 下）", () => {
    expect(hrRoutes).toHaveLength(1);
    expect(hrRoutes[0].path).toBe("hr");
    expect(hrRoutes[0].name).toBe("HrRoot");
  });

  it("子路由均要求认证并带标题", () => {
    for (const child of hrRoutes[0].children ?? []) {
      expect(child.meta?.requiresAuth).toBe(true);
      expect(child.meta?.title).toBeTruthy();
    }
  });

  it("路由路径与后端菜单 20 叶一致", () => {
    // module.py 菜单叶 path（组节点 path 空串不入列）
    const expected = [
      // 员工中心
      "/hr/employees",
      "/hr/positions",
      "/hr/employee-changes",
      // 考勤假期
      "/hr/attendance",
      "/hr/leave",
      // 招聘管理
      "/hr/requisitions",
      "/hr/candidates",
      "/hr/interviews",
      "/hr/channels",
      // 薪酬管理
      "/hr/salary-items",
      "/hr/salary-bands",
      "/hr/salary-packages",
      "/hr/payroll-runs",
      // 绩效管理（二期批 B/C）
      "/hr/perf-cycles",
      "/hr/perf-reviews",
      // 审批中心（二期批 A）
      "/hr/approvals",
      // 报表与自助（顶级菜单）
      "/hr/reports",
      "/hr/self-service",
      "/hr/my-leave",
      // 团队工作台（二期批 E）
      "/hr/team",
    ];
    const routePaths = (hrRoutes[0].children ?? []).map(
      (child) => `/${hrRoutes[0].path}/${child.path}`,
    );
    expect(routePaths).toEqual(expected);
  });

  it("权限叶 meta.permissions 与 module.py 权限码一致", () => {
    const children = hrRoutes[0].children ?? [];
    const byPath = new Map(children.map((child) => [child.path, child]));
    const expectedPermissions: Record<string, string[]> = {
      employees: ["hr:employee:read"],
      positions: ["hr:position:read"],
      "employee-changes": ["hr:employee_change:read"],
      attendance: ["hr:attendance:read"],
      leave: ["hr:leave:read"],
      requisitions: ["hr:requisition:read"],
      candidates: ["hr:candidate:read"],
      interviews: ["hr:interview:read"],
      channels: ["hr:channel:read"],
      "salary-items": ["hr:salary_item:read"],
      "salary-bands": ["hr:salary_band:read"],
      "salary-packages": ["hr:salary_package:read"],
      "payroll-runs": ["hr:payroll:read"],
      "perf-cycles": ["hr:perf_cycle:read"],
      "perf-reviews": ["hr:perf_review:read"],
      approvals: ["hr:approval:read"],
      reports: ["hr:report:read"],
    };
    for (const [path, permissions] of Object.entries(expectedPermissions)) {
      expect(byPath.get(path)?.meta?.permissions).toEqual(permissions);
    }
  });

  it("console 层叶（员工自助/我的假期/团队工作台）不挂权限码", () => {
    const children = hrRoutes[0].children ?? [];
    for (const path of ["self-service", "my-leave", "team"]) {
      const child = children.find((item) => item.path === path);
      expect(child?.meta?.permissions).toBeUndefined();
    }
  });
});
