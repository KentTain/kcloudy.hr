/**
 * PositionsPage 页面测试：列表/组织树加载、权限控制新增按钮、组织筛选联动
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PositionsPage from "@/hr/pages/positions/PositionsPage.vue";
import type { OrgTreeNode } from "@/hr/types/employee";
import type { Position } from "@/hr/types/position";

const permState = vi.hoisted(() => ({ granted: new Set<string>(["hr:position:read"]) }));

const apiMocks = vi.hoisted(() => ({
  listPositions: vi.fn(),
  getPosition: vi.fn(),
  createPosition: vi.fn(),
  updatePosition: vi.fn(),
  deletePosition: vi.fn(),
  getOrgTree: vi.fn(),
  getPositionOptions: vi.fn(),
  listEmployeeSalaryPackages: vi.fn(),
  getBandComparison: vi.fn(),
  listSalaryItemOptions: vi.fn(),
  listEmployees: vi.fn(),
}));

vi.mock("@/hr/api/position", () => ({
  listPositions: apiMocks.listPositions,
  getPosition: apiMocks.getPosition,
  createPosition: apiMocks.createPosition,
  updatePosition: apiMocks.updatePosition,
  deletePosition: apiMocks.deletePosition,
}));

vi.mock("@/hr/api/reference", () => ({
  getOrgTree: apiMocks.getOrgTree,
  getPositionOptions: apiMocks.getPositionOptions,
  listEmployeeSalaryPackages: apiMocks.listEmployeeSalaryPackages,
  getBandComparison: apiMocks.getBandComparison,
  listSalaryItemOptions: apiMocks.listSalaryItemOptions,
}));

vi.mock("@/hr/api/employee", () => ({
  listEmployees: apiMocks.listEmployees,
}));

vi.mock("@/framework/stores", () => ({
  useUserStore: () => ({
    hasPermission: (code: string) => permState.granted.has(code),
  }),
}));

vi.mock("@/framework/utils/feedback", () => ({
  confirmAction: vi.fn(async () => true),
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

const POSITIONS: Position[] = [
  {
    id: "pos-1",
    code: "BE",
    name: "后端工程师",
    org_id: "org-1",
    job_level: "P5",
    headcount: 10,
    active_employee_count: 3,
    status: "active",
  },
  {
    id: "pos-2",
    code: "FE",
    name: "前端工程师",
    org_id: null,
    job_level: null,
    headcount: null,
    active_employee_count: 0,
    status: "disabled",
  },
];

const ORG_TREE: OrgTreeNode[] = [
  { id: "org-1", name: "总公司", children: [{ id: "org-2", name: "研发部", children: [] }] },
];

function mountPage() {
  return mount(PositionsPage, { attachTo: document.body });
}

beforeEach(() => {
  vi.resetAllMocks();
  permState.granted = new Set(["hr:position:read", "hr:position:write", "hr:position:delete"]);
  apiMocks.listPositions.mockResolvedValue({ code: 200, data: POSITIONS, total: 2, page: 1, page_size: 20 });
  apiMocks.getOrgTree.mockResolvedValue({ code: 200, data: ORG_TREE });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("PositionsPage", () => {
  it("挂载后拉取岗位列表与组织树，并渲染行数据", async () => {
    mountPage();
    await flushPromises();

    expect(apiMocks.listPositions).toHaveBeenCalled();
    expect(apiMocks.getOrgTree).toHaveBeenCalled();
    const body = document.body.textContent ?? "";
    expect(body).toContain("后端工程师");
    expect(body).toContain("10 / 3");
  });

  it("新增岗位按钮随 hr:position:write 权限显隐", async () => {
    const withPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-create-position"]')).toBeTruthy();
    withPerm.unmount();
    document.body.innerHTML = "";

    permState.granted = new Set(["hr:position:read"]);
    const withoutPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-create-position"]')).toBeNull();
    withoutPerm.unmount();
  });

  it("组织树点击筛选联动岗位列表", async () => {
    mountPage();
    await flushPromises();

    const node = document.querySelector('[data-testid="org-tree-node"]') as HTMLElement;
    expect(node).toBeTruthy();
    node.click();
    await flushPromises();

    const lastQuery = apiMocks.listPositions.mock.calls.at(-1)[0];
    expect(lastQuery.org_id).toBe("org-1");
  });
});
