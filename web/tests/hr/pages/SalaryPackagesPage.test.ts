/**
 * SalaryPackagesPage 页面测试：员工列表（离职过滤）与方案详情主从加载、
 * 薪带对标提示、调薪弹窗预填与提交载荷、生效日期早于当日拦截、写权限显隐
 */
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DateInput from "@/components/common/form/date-input/DateInput.vue";
import SalaryPackagesPage from "@/hr/pages/salary-packages/SalaryPackagesPage.vue";
import type { Employee, SalaryPackageRecord } from "@/hr/types/employee";

const permState = vi.hoisted(() => ({
  granted: new Set<string>(["hr:salary_package:read", "hr:salary_package:write"]),
}));

const apiMocks = vi.hoisted(() => ({
  getBandComparison: vi.fn(),
  listEmployeeSalaryPackages: vi.fn(),
  getOrgTree: vi.fn(),
  getPositionOptions: vi.fn(),
  listSalaryItemOptions: vi.fn(),
  listEmployees: vi.fn(),
  adjustSalaryPackage: vi.fn(),
}));

vi.mock("@/hr/api/reference", () => ({
  getBandComparison: apiMocks.getBandComparison,
  listEmployeeSalaryPackages: apiMocks.listEmployeeSalaryPackages,
  getOrgTree: apiMocks.getOrgTree,
  getPositionOptions: apiMocks.getPositionOptions,
  listSalaryItemOptions: apiMocks.listSalaryItemOptions,
}));

vi.mock("@/hr/api/employee", () => ({
  listEmployees: apiMocks.listEmployees,
}));

vi.mock("@/hr/api/salary", () => ({
  adjustSalaryPackage: apiMocks.adjustSalaryPackage,
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
    gender: null,
    phone: null,
    work_email: null,
    org_id: "org-1",
    position_id: "pos-1",
    job_level: "P5",
    status: "regular",
    hire_date: "2025-03-01",
    regular_date: null,
    offboard_date: null,
    user_id: null,
    has_account: true,
  },
  {
    id: "emp-2",
    employee_no: "EMP002",
    name: "李四",
    gender: null,
    phone: null,
    work_email: null,
    org_id: "org-1",
    position_id: "pos-1",
    job_level: "P4",
    status: "offboarded",
    hire_date: "2024-01-01",
    regular_date: null,
    offboard_date: "2026-09-30",
    user_id: null,
    has_account: true,
  },
];

const PACKAGES: SalaryPackageRecord[] = [
  {
    id: "pkg-2",
    employee_id: "emp-1",
    item_id: "it-1",
    item_code: "base_monthly",
    item_name: "月度基本工资",
    category: "base",
    amount: 18000,
    reason: "adjust",
    effective_from: "2026-01-01",
    effective_to: null,
  },
  {
    id: "pkg-1",
    employee_id: "emp-1",
    item_id: "it-1",
    item_code: "base_monthly",
    item_name: "月度基本工资",
    category: "base",
    amount: 16000,
    reason: "hire",
    effective_from: "2025-03-01",
    effective_to: "2025-12-31",
  },
];

function mountPage() {
  return mount(SalaryPackagesPage, { attachTo: document.body });
}

function setInputValue(selector: string, value: string) {
  const host = document.querySelector(selector);
  const input = host?.querySelector("input") ?? host;
  if (input instanceof HTMLInputElement) {
    input.value = value;
    input.dispatchEvent(new Event("input"));
  }
}

function clickButton(testid: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  if (el instanceof HTMLElement) el.click();
}

function todayStr(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

beforeEach(() => {
  vi.resetAllMocks();
  permState.granted = new Set(["hr:salary_package:read", "hr:salary_package:write"]);
  apiMocks.listEmployees.mockResolvedValue({ code: 200, data: EMPLOYEES });
  apiMocks.getOrgTree.mockResolvedValue({
    code: 200,
    data: [{ id: "org-1", name: "研发部", children: [] }],
  });
  apiMocks.getPositionOptions.mockResolvedValue({
    code: 200,
    data: [{ id: "pos-1", name: "后端工程师", code: "BE", job_level: "P5", status: "active" }],
  });
  apiMocks.listEmployeeSalaryPackages.mockResolvedValue({ code: 200, data: PACKAGES });
  apiMocks.getBandComparison.mockResolvedValue({
    code: 200,
    data: { job_level: "P5", total: 18000, band_min: 15000, band_max: 25000, position: "within" },
  });
  apiMocks.listSalaryItemOptions.mockResolvedValue({
    code: 200,
    data: [{ id: "it-1", name: "月度基本工资", code: "base_monthly", category: "base" }],
  });
  apiMocks.adjustSalaryPackage.mockResolvedValue({ code: 200, data: [] });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("SalaryPackagesPage", () => {
  it("挂载加载员工列表（过滤离职），选中后加载方案与薪带对标", async () => {
    mountPage();
    await flushPromises();

    expect(apiMocks.listEmployees).toHaveBeenCalled();
    const body = document.body.textContent ?? "";
    expect(body).toContain("张三");
    expect(body).not.toContain("李四");

    clickButton("package-employee-emp-1");
    await flushPromises();

    expect(apiMocks.listEmployeeSalaryPackages).toHaveBeenCalledWith("emp-1");
    expect(apiMocks.getBandComparison).toHaveBeenCalledWith("emp-1");
    const header = document.querySelector('[data-testid="package-employee-header"]')?.textContent ?? "";
    expect(header).toContain("带宽区间内");
    expect(header).toContain("18000.00") || expect(header).toContain("18,000.00");
    const history = document.querySelector('[data-testid="package-history"]')?.textContent ?? "";
    expect(history).toContain("2025-03-01 ~ 2025-12-31");
  });

  it("调薪弹窗预填当前方案并按载荷提交（原因/生效日）", async () => {
    mountPage();
    await flushPromises();
    clickButton("package-employee-emp-1");
    await flushPromises();

    clickButton("open-package-editor");
    await flushPromises();
    expect(apiMocks.listSalaryItemOptions).toHaveBeenCalled();

    const comparison = document.querySelector('[data-testid="package-comparison"]')?.textContent ?? "";
    expect(comparison).toContain("18000.00");

    setInputValue('[data-testid="package-amount-input-0"]', "20000");
    await flushPromises();
    clickButton("package-submit");
    await flushPromises();

    expect(apiMocks.adjustSalaryPackage).toHaveBeenCalledWith("emp-1", {
      items: [{ item_id: "it-1", amount: 20000 }],
      reason: "adjust",
      effective_from: todayStr(),
    });
  });

  it("生效日期早于当日被拦截，不发起提交", async () => {
    const wrapper: VueWrapper = mountPage();
    await flushPromises();
    clickButton("package-employee-emp-1");
    await flushPromises();
    clickButton("open-package-editor");
    await flushPromises();

    // DateInput 为 Popover 日历（触发 input 只读），经组件实例 emit 更新 v-model
    const dateInput = wrapper.findComponent(DateInput);
    expect(dateInput.exists()).toBe(true);
    dateInput.vm.$emit("update:modelValue", "2026-10-16");
    await flushPromises();
    clickButton("package-submit");
    await flushPromises();

    expect(apiMocks.adjustSalaryPackage).not.toHaveBeenCalled();
    const { notifyError } = await import("@/framework/utils/feedback");
    expect(notifyError).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining("早于当日") }));
  });

  it("发起调薪按钮随 hr:salary_package:write 权限显隐", async () => {
    const withPerm = mountPage();
    await flushPromises();
    const editorButton = document.querySelector<HTMLButtonElement>('[data-testid="open-package-editor"]');
    expect(editorButton?.disabled).toBe(true);
    withPerm.unmount();
    document.body.innerHTML = "";

    permState.granted = new Set(["hr:salary_package:read"]);
    const withoutPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-package-editor"]')).toBeNull();
    withoutPerm.unmount();
  });
});
