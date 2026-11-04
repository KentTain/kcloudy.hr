/**
 * EmployeeChangesPage 页面测试：流水与参照加载、变更摘要渲染、
 * 发起异动按钮权限显隐、详情侧滑前后对比
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import EmployeeChangesPage from "@/hr/pages/employee-changes/EmployeeChangesPage.vue";
import type { ChangeRecord, Employee, OrgTreeNode } from "@/hr/types/employee";

const permState = vi.hoisted(() => ({ granted: new Set<string>(["hr:employee_change:read"]) }));

const apiMocks = vi.hoisted(() => ({
  listChangeRecords: vi.fn(),
  getChangeRecord: vi.fn(),
  transferChangeRecord: vi.fn(),
  listEmployees: vi.fn(),
  createChange: vi.fn(),
  getOrgTree: vi.fn(),
  getPositionOptions: vi.fn(),
  listSalaryItemOptions: vi.fn(),
}));

vi.mock("@/hr/api/change", () => ({
  listChangeRecords: apiMocks.listChangeRecords,
  getChangeRecord: apiMocks.getChangeRecord,
  transferChangeRecord: apiMocks.transferChangeRecord,
}));

vi.mock("@/hr/api/employee", () => ({
  listEmployees: apiMocks.listEmployees,
  createChange: apiMocks.createChange,
}));

vi.mock("@/hr/api/reference", () => ({
  getOrgTree: apiMocks.getOrgTree,
  getPositionOptions: apiMocks.getPositionOptions,
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
    phone: null,
    work_email: null,
    org_id: "org-1",
    position_id: "pos-1",
    job_level: "P5",
    status: "regular",
    hire_date: "2025-01-01",
    regular_date: null,
    offboard_date: null,
    user_id: null,
    has_account: true,
  },
];

const CHANGES: ChangeRecord[] = [
  {
    id: "ch-1",
    employee_id: "emp-1",
    change_type: "transfer",
    before_data: { org_id: "org-1", position_id: "pos-1", job_level: "P5", status: "regular" },
    after_data: { org_id: "org-2", position_id: "pos-1", job_level: "P5", status: "regular" },
    effective_date: "2026-01-01",
    operator_id: "user-9",
  },
];

const ORG_TREE: OrgTreeNode[] = [
  { id: "org-1", name: "总公司", children: [{ id: "org-2", name: "研发部", children: [] }] },
];

function mountPage() {
  return mount(EmployeeChangesPage, {
    attachTo: document.body,
    global: { stubs: { PeopleSelectDialog: true } },
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  permState.granted = new Set([
    "hr:employee_change:read",
    "hr:employee_change:write",
    "hr:employee_change:transfer",
  ]);
  apiMocks.transferChangeRecord.mockResolvedValue({ code: 200, data: null });
  apiMocks.listChangeRecords.mockResolvedValue({
    code: 200,
    data: CHANGES,
    total: 1,
    page: 1,
    page_size: 20,
  });
  apiMocks.listEmployees.mockResolvedValue({
    code: 200,
    data: EMPLOYEES,
    total: 1,
    page: 1,
    page_size: 200,
  });
  apiMocks.getOrgTree.mockResolvedValue({ code: 200, data: ORG_TREE });
  apiMocks.getPositionOptions.mockResolvedValue({
    code: 200,
    data: [{ id: "pos-1", name: "后端工程师", code: "BE", job_level: "P5", status: "active" }],
  });
  apiMocks.listSalaryItemOptions.mockResolvedValue({ code: 200, data: [] });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("EmployeeChangesPage", () => {
  it("挂载后拉取异动流水与参照数据（员工映射/组织/岗位）", async () => {
    mountPage();
    await flushPromises();

    expect(apiMocks.listChangeRecords).toHaveBeenCalled();
    expect(apiMocks.listEmployees).toHaveBeenCalled();
    expect(apiMocks.getOrgTree).toHaveBeenCalled();
    expect(apiMocks.getPositionOptions).toHaveBeenCalled();
  });

  it("列表渲染员工与变更摘要（组织名称解析）", async () => {
    mountPage();
    await flushPromises();

    const body = document.body.textContent ?? "";
    expect(body).toContain("EMP001 张三");
    expect(body).toContain("组织：总公司 → 研发部");
  });

  it("发起异动按钮随 hr:employee_change:write 权限显隐", async () => {
    const withPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-change-picker"]')).toBeTruthy();
    withPerm.unmount();
    document.body.innerHTML = "";

    permState.granted = new Set(["hr:employee_change:read"]);
    const withoutPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-change-picker"]')).toBeNull();
    withoutPerm.unmount();
  });

  it("点击详情打开侧滑并渲染前后对比", async () => {
    mountPage();
    await flushPromises();

    const link = document.querySelector('[data-testid="change-detail-link"]') as HTMLElement;
    expect(link).toBeTruthy();
    link.click();
    await flushPromises();

    const drawer = document.querySelector('[data-testid="change-detail-drawer"]');
    expect(drawer).toBeTruthy();
    expect(drawer?.textContent).toContain("组织：总公司 → 研发部");
    expect(drawer?.textContent).toContain("生效日期");
  });

  it("移交按钮随权限显隐，选择人员确认后调移交接口并刷新", async () => {
    const wrapper = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="change-transfer-ch-1"]')).toBeTruthy();

    (document.querySelector('[data-testid="change-transfer-ch-1"]') as HTMLElement).click();
    await flushPromises();

    const dialog = wrapper.findComponent({ name: "PeopleSelectDialog" });
    expect(dialog.exists()).toBe(true);
    expect(dialog.props("open")).toBe(true);

    dialog.vm.$emit(
      "confirm",
      ["u-7"],
      [{ id: "u-7", username: "wangwu", nickname: "王五", status: "active" }]
    );
    await flushPromises();

    expect(apiMocks.transferChangeRecord).toHaveBeenCalledWith("ch-1", "u-7");
    expect(apiMocks.listChangeRecords).toHaveBeenCalledTimes(2);
    wrapper.unmount();
    document.body.innerHTML = "";

    permState.granted = new Set(["hr:employee_change:read", "hr:employee_change:write"]);
    const noPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="change-transfer-ch-1"]')).toBeNull();
    noPerm.unmount();
  });
});
