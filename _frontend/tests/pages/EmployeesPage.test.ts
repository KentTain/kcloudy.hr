/**
 * EmployeesPage 页面测试：列表/统计/组织树加载、权限控制按钮显隐
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import EmployeesPage from "@/hr/pages/employees/EmployeesPage.vue";
import type { Employee, EmployeeStats, OrgTreeNode, PositionOption } from "@/hr/types/employee";

const permState = vi.hoisted(() => ({ granted: new Set<string>(["hr:employee:read"]) }));

const apiMocks = vi.hoisted(() => ({
  listEmployees: vi.fn(),
  getEmployeeStats: vi.fn(),
  getEmployeeDetail: vi.fn(),
  getSensitiveView: vi.fn(),
  createEmployee: vi.fn(),
  updateEmployee: vi.fn(),
  deleteEmployee: vi.fn(),
  importEmployees: vi.fn(),
  openAccount: vi.fn(),
  getEmployeeAttributes: vi.fn(),
  saveEmployeeAttributes: vi.fn(),
  listEmployeeChanges: vi.fn(),
  createChange: vi.fn(),
  listEmployeeContracts: vi.fn(),
  createContract: vi.fn(),
  renewContract: vi.fn(),
  terminateContract: vi.fn(),
  deleteContract: vi.fn(),
  listEmployeeAttachments: vi.fn(),
  uploadEmployeeAttachment: vi.fn(),
  getAttachmentDownloadUrl: vi.fn(),
  deleteAttachment: vi.fn(),
  listFieldGroups: vi.fn(),
  createFieldGroup: vi.fn(),
  updateFieldGroup: vi.fn(),
  deleteFieldGroup: vi.fn(),
  listFieldDefinitions: vi.fn(),
  createFieldDefinition: vi.fn(),
  updateFieldDefinition: vi.fn(),
  deleteFieldDefinition: vi.fn(),
  getOrgTree: vi.fn(),
  getPositionOptions: vi.fn(),
  listEmployeeSalaryPackages: vi.fn(),
  getBandComparison: vi.fn(),
  listSalaryItemOptions: vi.fn(),
}));

vi.mock("@/hr/api/employee", () => ({
  listEmployees: apiMocks.listEmployees,
  getEmployeeStats: apiMocks.getEmployeeStats,
  getEmployeeDetail: apiMocks.getEmployeeDetail,
  getSensitiveView: apiMocks.getSensitiveView,
  createEmployee: apiMocks.createEmployee,
  updateEmployee: apiMocks.updateEmployee,
  deleteEmployee: apiMocks.deleteEmployee,
  importEmployees: apiMocks.importEmployees,
  openAccount: apiMocks.openAccount,
  getEmployeeAttributes: apiMocks.getEmployeeAttributes,
  saveEmployeeAttributes: apiMocks.saveEmployeeAttributes,
  listEmployeeChanges: apiMocks.listEmployeeChanges,
  createChange: apiMocks.createChange,
}));

vi.mock("@/hr/api/contract", () => ({
  listEmployeeContracts: apiMocks.listEmployeeContracts,
  createContract: apiMocks.createContract,
  renewContract: apiMocks.renewContract,
  terminateContract: apiMocks.terminateContract,
  deleteContract: apiMocks.deleteContract,
  listEmployeeAttachments: apiMocks.listEmployeeAttachments,
  uploadEmployeeAttachment: apiMocks.uploadEmployeeAttachment,
  getAttachmentDownloadUrl: apiMocks.getAttachmentDownloadUrl,
  deleteAttachment: apiMocks.deleteAttachment,
}));

vi.mock("@/hr/api/field", () => ({
  listFieldGroups: apiMocks.listFieldGroups,
  createFieldGroup: apiMocks.createFieldGroup,
  updateFieldGroup: apiMocks.updateFieldGroup,
  deleteFieldGroup: apiMocks.deleteFieldGroup,
  listFieldDefinitions: apiMocks.listFieldDefinitions,
  createFieldDefinition: apiMocks.createFieldDefinition,
  updateFieldDefinition: apiMocks.updateFieldDefinition,
  deleteFieldDefinition: apiMocks.deleteFieldDefinition,
}));

vi.mock("@/hr/api/reference", () => ({
  getOrgTree: apiMocks.getOrgTree,
  getPositionOptions: apiMocks.getPositionOptions,
  listEmployeeSalaryPackages: apiMocks.listEmployeeSalaryPackages,
  getBandComparison: apiMocks.getBandComparison,
  listSalaryItemOptions: apiMocks.listSalaryItemOptions,
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

const EMPLOYEES: Employee[] = [
  {
    id: "emp-1",
    employee_no: "EMP001",
    name: "张三",
    gender: "male",
    phone: "13800000000",
    work_email: null,
    org_id: "org-1",
    position_id: null,
    job_level: "P5",
    status: "regular",
    hire_date: "2025-01-01",
    regular_date: null,
    offboard_date: null,
    user_id: null,
    has_account: true,
  },
];

const STATS: EmployeeStats = {
  active_count: 42,
  probation_count: 5,
  month_hired_count: 3,
  turnover_rate: 0.052,
};

const ORG_TREE: OrgTreeNode[] = [
  { id: "org-1", name: "总公司", children: [{ id: "org-2", name: "研发部", children: [] }] },
];

const POSITIONS: PositionOption[] = [{ id: "pos-1", name: "后端工程师", code: "BE", job_level: "P5", status: "active" }];

function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/:pathMatch(.*)*", component: { template: "<div/>" } }],
  });
  return mount(EmployeesPage, { attachTo: document.body, global: { plugins: [router] } });
}

beforeEach(() => {
  vi.resetAllMocks();
  permState.granted = new Set([
    "hr:employee:read",
    "hr:employee:write",
    "hr:employee:import",
    "hr:employee:delete",
    "hr:field_definition:write",
    "hr:contract:read",
    "hr:attachment:read",
    "hr:salary_package:read",
  ]);
  apiMocks.getEmployeeDetail.mockResolvedValue({ code: 200, data: EMPLOYEES[0] });
  apiMocks.listEmployees.mockResolvedValue({ code: 200, data: EMPLOYEES, total: 1, page: 1, page_size: 20 });
  apiMocks.getEmployeeStats.mockResolvedValue({ code: 200, data: STATS });
  apiMocks.getOrgTree.mockResolvedValue({ code: 200, data: ORG_TREE });
  apiMocks.getPositionOptions.mockResolvedValue({ code: 200, data: POSITIONS });
  apiMocks.listFieldGroups.mockResolvedValue({ code: 200, data: [] });
  apiMocks.listFieldDefinitions.mockResolvedValue({ code: 200, data: [] });
  apiMocks.listEmployeeChanges.mockResolvedValue({ code: 200, data: [] });
  apiMocks.listEmployeeContracts.mockResolvedValue({ code: 200, data: [] });
  apiMocks.listEmployeeAttachments.mockResolvedValue({ code: 200, data: [] });
  apiMocks.listEmployeeSalaryPackages.mockResolvedValue({ code: 200, data: [] });
  apiMocks.getBandComparison.mockResolvedValue({ code: 200, data: null });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("EmployeesPage", () => {
  it("挂载后拉取列表/统计/组织树/岗位选项", async () => {
    mountPage();
    await flushPromises();

    expect(apiMocks.listEmployees).toHaveBeenCalled();
    expect(apiMocks.getEmployeeStats).toHaveBeenCalled();
    expect(apiMocks.getOrgTree).toHaveBeenCalled();
    expect(apiMocks.getPositionOptions).toHaveBeenCalled();
  });

  it("统计卡渲染四项指标", async () => {
    mountPage();
    await flushPromises();

    const cards = document.querySelectorAll('[data-testid="employee-stat-cards"] > div');
    expect(cards.length).toBe(4);
    expect(cards[0].textContent).toContain("42");
    expect(cards[3].textContent).toContain("5.2%");
  });

  it("导入按钮随 hr:employee:import 权限显隐", async () => {
    const withPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-import-modal"]')).toBeTruthy();
    withPerm.unmount();

    permState.granted = new Set(["hr:employee:read"]);
    const withoutPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-import-modal"]')).toBeNull();
    // 建档按钮同样受 hr:employee:write 控制
    expect(document.querySelector('[data-testid="open-create-modal"]')).toBeNull();
    withoutPerm.unmount();
  });

  it("组织树点击筛选联动统计与列表", async () => {
    mountPage();
    await flushPromises();

    const node = document.querySelector('[data-testid="org-tree-node"]') as HTMLElement;
    expect(node).toBeTruthy();
    node.click();
    await flushPromises();

    expect(apiMocks.getEmployeeStats).toHaveBeenCalledWith("org-1");
    const lastQuery = apiMocks.listEmployees.mock.calls.at(-1)[0];
    expect(lastQuery.org_id).toBe("org-1");
  });

  it("路由携带 employee_id 时自动打开详情抽屉", async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: "/:pathMatch(.*)*", component: { template: "<div/>" } }],
    });
    await router.push("/hr/employees?employee_id=emp-1");
    mount(EmployeesPage, { attachTo: document.body, global: { plugins: [router] } });
    await flushPromises();

    expect(apiMocks.getEmployeeDetail).toHaveBeenCalledWith("emp-1");
    expect(document.querySelector('[data-testid="drawer-header"]')?.textContent).toContain("张三");
  });
});
