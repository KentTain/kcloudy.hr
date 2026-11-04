/**
 * EmployeeDetailDrawer 单元测试：打开加载、状态渲染、Tab 懒加载、
 * 薪酬 Tab 权限显隐、切换条
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import EmployeeDetailDrawer from "@/hr/components/employee/EmployeeDetailDrawer.vue";
import type { Employee } from "@/hr/types/employee";

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

const DETAIL = {
  id: "emp-1",
  employee_no: "EMP001",
  name: "张三",
  gender: "male",
  phone: "13800000000",
  work_email: "zhang@company.com",
  org_id: "org-1",
  position_id: "pos-1",
  job_level: "P5",
  status: "probation",
  hire_date: "2025-01-01",
  regular_date: null,
  offboard_date: null,
  user_id: null,
  has_account: true,
  birth_date: "1995-01-01",
  id_card_masked: "110101********1234",
  bank_card_masked: null,
};

const EMPLOYEES: Employee[] = [
  { ...DETAIL, hire_date: "2025-01-01" },
  { ...DETAIL, id: "emp-2", name: "李四", employee_no: "EMP002" },
];

const CHANGES = [
  { id: "ch-1", employee_id: "emp-1", change_type: "hire", before_data: null, after_data: { org_id: "org-1" }, effective_date: "2025-01-01", operator_id: null },
];

function mountDrawer(granted: string[]) {
  permState.granted = new Set(granted);
  const onSwitch = vi.fn();
  const wrapper = mount(EmployeeDetailDrawer, {
    props: {
      open: true,
      employeeId: "emp-1",
      employees: EMPLOYEES,
      "onUpdate:open": vi.fn(),
      onRefresh: vi.fn(),
      onSwitch,
    },
    attachTo: document.body,
  });
  return { wrapper, onSwitch };
}

const BASE_PERMS = ["hr:employee:read", "hr:employee:write", "hr:contract:read", "hr:attachment:read"];

beforeEach(() => {
  vi.resetAllMocks();
  apiMocks.getEmployeeDetail.mockResolvedValue({ code: 200, data: DETAIL });
  apiMocks.listEmployeeChanges.mockResolvedValue({ code: 200, data: CHANGES });
  apiMocks.getEmployeeAttributes.mockResolvedValue({ code: 200, data: [] });
  apiMocks.listFieldGroups.mockResolvedValue({ code: 200, data: [] });
  apiMocks.listFieldDefinitions.mockResolvedValue({ code: 200, data: [] });
  apiMocks.listEmployeeContracts.mockResolvedValue({ code: 200, data: [] });
  apiMocks.listEmployeeAttachments.mockResolvedValue({ code: 200, data: [] });
  apiMocks.listEmployeeSalaryPackages.mockResolvedValue({ code: 200, data: [] });
  apiMocks.getBandComparison.mockResolvedValue({ code: 200, data: null });
  apiMocks.getOrgTree.mockResolvedValue({
    code: 200,
    data: [{ id: "org-1", name: "研发部", children: [] }],
  });
  apiMocks.getPositionOptions.mockResolvedValue({
    code: 200,
    data: [{ id: "pos-1", name: "后端工程师", code: "BE", job_level: null, status: "active" }],
  });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("EmployeeDetailDrawer", () => {
  it("打开后加载详情并渲染头部（状态徽标/工号/组织·岗位解析）", async () => {
    mountDrawer(BASE_PERMS);
    await flushPromises();

    expect(apiMocks.getEmployeeDetail).toHaveBeenCalledWith("emp-1");
    const header = document.querySelector('[data-testid="drawer-header"]');
    expect(header?.textContent).toContain("张三");
    expect(header?.textContent).toContain("EMP001");
    expect(header?.textContent).toContain("试用期");
    expect(header?.textContent).toContain("研发部");
    expect(header?.textContent).toContain("后端工程师");
  });

  it("概览 Tab 渲染成长记录时间线", async () => {
    mountDrawer(BASE_PERMS);
    await flushPromises();

    expect(apiMocks.listEmployeeChanges).toHaveBeenCalledWith("emp-1", { page: 1, page_size: 50 });
    expect(document.querySelector('[data-testid="drawer-timeline"]')?.textContent).toContain("入职");
  });

  it("无薪酬权限时薪酬 Tab 隐藏，有权限时懒加载定薪数据", async () => {
    const { wrapper: withoutSalary } = mountDrawer(BASE_PERMS);
    await flushPromises();
    expect(document.querySelector('[data-testid="drawer-tab-salary"]')).toBeNull();
    withoutSalary.unmount();
    document.body.innerHTML = "";

    vi.clearAllMocks();
    apiMocks.getEmployeeDetail.mockResolvedValue({ code: 200, data: DETAIL });
    apiMocks.listEmployeeChanges.mockResolvedValue({ code: 200, data: [] });

    mountDrawer([...BASE_PERMS, "hr:salary_package:read"]);
    await flushPromises();

    const salaryTab = document.querySelector('[data-testid="drawer-tab-salary"]') as HTMLElement;
    expect(salaryTab).toBeTruthy();
    // reka TabsTrigger 由 mousedown 触发
    salaryTab.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    await flushPromises();

    expect(apiMocks.listEmployeeSalaryPackages).toHaveBeenCalledWith("emp-1");
    expect(apiMocks.getBandComparison).toHaveBeenCalledWith("emp-1");
  });

  it("切换条显示 i/n 并可翻页", async () => {
    const { onSwitch } = mountDrawer(BASE_PERMS);
    await flushPromises();

    const index = document.querySelector('[data-testid="employee-switch-index"]');
    expect(index?.textContent?.replace(/\s/g, "")).toBe("1/2");

    const next = document.querySelector('[data-testid="employee-switch-next"]') as HTMLButtonElement;
    next.click();
    await flushPromises();

    expect(onSwitch).toHaveBeenCalledTimes(1);
    expect(onSwitch.mock.calls[0][0].id).toBe("emp-2");
  });
});
