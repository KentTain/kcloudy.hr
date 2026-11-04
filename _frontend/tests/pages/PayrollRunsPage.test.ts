/**
 * PayrollRunsPage 页面测试：批次列表渲染、创建批次（期间载荷+任务回告）、
 * 明细矩阵构建（员工×项列/小计/合计）、修正弹窗（无备注拦截+载荷）、
 * 确认操作与取消按钮状态边界、写权限显隐
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PayrollRunsPage from "@/hr/pages/payroll-runs/PayrollRunsPage.vue";
import type { PayrollEntry, PayrollRun } from "@/hr/types/salary";

const permState = vi.hoisted(() => ({
  granted: new Set<string>(["hr:payroll:read", "hr:payroll:write", "hr:payroll:confirm"]),
}));

const downloadMocks = vi.hoisted(() => ({
  downloadBase64File: vi.fn(),
}));

vi.mock("@/hr/utils/download", () => ({
  downloadBase64File: downloadMocks.downloadBase64File,
}));

const apiMocks = vi.hoisted(() => ({
  listPayrollRuns: vi.fn(),
  createPayrollRun: vi.fn(),
  getPayrollRun: vi.fn(),
  listPayrollEntries: vi.fn(),
  updatePayrollEntry: vi.fn(),
  confirmPayrollRun: vi.fn(),
  payPayrollRun: vi.fn(),
  cancelPayrollRun: vi.fn(),
  exportPayrollRun: vi.fn(),
}));

vi.mock("@/hr/api/salary", () => ({
  listPayrollRuns: apiMocks.listPayrollRuns,
  createPayrollRun: apiMocks.createPayrollRun,
  getPayrollRun: apiMocks.getPayrollRun,
  listPayrollEntries: apiMocks.listPayrollEntries,
  updatePayrollEntry: apiMocks.updatePayrollEntry,
  confirmPayrollRun: apiMocks.confirmPayrollRun,
  payPayrollRun: apiMocks.payPayrollRun,
  cancelPayrollRun: apiMocks.cancelPayrollRun,
  exportPayrollRun: apiMocks.exportPayrollRun,
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

const RUNS: PayrollRun[] = [
  { id: "run-1", period: "2026-10", status: "draft", total_amount: 45500, employee_count: 2, pay_date: null },
  { id: "run-2", period: "2026-09", status: "paid", total_amount: 44000, employee_count: 2, pay_date: "2026-09-25" },
];

const ENTRIES: PayrollEntry[] = [
  { id: "entry-1", run_id: "run-1", employee_id: "emp-1", employee_no: "EMP001", employee_name: "张三", item_id: "it-1", item_code: "base_monthly", amount: 18000, note: null },
  { id: "entry-2", run_id: "run-1", employee_id: "emp-1", employee_no: "EMP001", employee_name: "张三", item_id: "it-2", item_code: "perf_monthly", amount: 5000, note: null },
  { id: "entry-3", run_id: "run-1", employee_id: "emp-2", employee_no: "EMP002", employee_name: "李四", item_id: "it-1", item_code: "base_monthly", amount: 22500, note: null },
];

function mountPage() {
  return mount(PayrollRunsPage, { attachTo: document.body });
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

beforeEach(() => {
  vi.resetAllMocks();
  permState.granted = new Set(["hr:payroll:read", "hr:payroll:write", "hr:payroll:confirm"]);
  apiMocks.listPayrollRuns.mockResolvedValue({ code: 200, data: RUNS, total: 2, page: 1, page_size: 50 });
  apiMocks.listPayrollEntries.mockResolvedValue({ code: 200, data: ENTRIES, total: 3, page: 1, page_size: 200 });
  apiMocks.createPayrollRun.mockResolvedValue({
    code: 200,
    data: { run: RUNS[0], task_id: "task-payroll-1" },
  });
  apiMocks.updatePayrollEntry.mockResolvedValue({
    code: 200,
    data: { ...ENTRIES[0], amount: 18500, note: "补发差额定额" },
  });
  apiMocks.confirmPayrollRun.mockResolvedValue({ code: 200, data: { ...RUNS[0], status: "confirmed" } });
  apiMocks.cancelPayrollRun.mockResolvedValue({ code: 200, data: RUNS[0] });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("PayrollRunsPage", () => {
  it("挂载渲染批次列表（期间/状态/总额/人数），已发放批次无取消按钮", async () => {
    mountPage();
    await flushPromises();

    expect(apiMocks.listPayrollRuns).toHaveBeenCalled();
    const body = document.body.textContent ?? "";
    expect(body).toContain("2026-10");
    expect(body).toContain("草稿");
    expect(body).toContain("已发放");
    expect(body).toContain("45,500.00");
    expect(document.querySelector('[data-testid="run-cancel-run-1"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="run-cancel-run-2"]')).toBeNull();
  });

  it("创建批次提交期间并回告任务 ID", async () => {
    mountPage();
    await flushPromises();

    clickButton("open-create-run");
    await flushPromises();
    expect(document.querySelector('[data-testid="create-run-dialog"]')).toBeTruthy();

    const periodHost = document.querySelector('[data-testid="create-run-period"]');
    const periodInput = (periodHost?.querySelector("input") ?? periodHost) as HTMLInputElement | null;
    expect(periodInput?.value).toMatch(/^\d{4}-\d{2}$/);

    clickButton("create-run-submit");
    await flushPromises();

    expect(apiMocks.createPayrollRun).toHaveBeenCalledWith(expect.stringMatching(/^\d{4}-\d{2}$/));
    const { notifySuccess } = await import("@/framework/utils/feedback");
    expect(notifySuccess).toHaveBeenCalledWith(expect.stringContaining("task-payroll-1"));
  });

  it("进入明细构建矩阵：员工行 × 项列、行小计与列合计", async () => {
    mountPage();
    await flushPromises();

    clickButton("run-detail-run-1");
    await flushPromises();

    expect(apiMocks.listPayrollEntries).toHaveBeenCalledWith("run-1");
    const matrix = document.querySelector('[data-testid="payroll-matrix"]')?.textContent ?? "";
    expect(matrix).toContain("张三（EMP001）");
    expect(matrix).toContain("base_monthly");
    expect(matrix).toContain("23,000.00");
    expect(matrix).toContain("40,500.00");

    const rows = document.querySelectorAll('[data-testid="matrix-row"]');
    expect(rows.length).toBe(2);
    expect(document.querySelector('[data-testid="matrix-footer"]')?.textContent).toContain("45,500.00");
  });

  it("草稿批次单元格修正：金额修改无备注被拦截，补备注后提交载荷", async () => {
    mountPage();
    await flushPromises();
    clickButton("run-detail-run-1");
    await flushPromises();

    clickButton("matrix-cell-emp-1-it-1");
    await flushPromises();
    expect(document.querySelector('[data-testid="entry-edit-dialog"]')).toBeTruthy();

    setInputValue('[data-testid="entry-edit-amount"]', "18500");
    await flushPromises();
    clickButton("entry-edit-submit");
    await flushPromises();

    expect(apiMocks.updatePayrollEntry).not.toHaveBeenCalled();

    setInputValue('[data-testid="entry-edit-note"]', "补发差额定额");
    await flushPromises();
    clickButton("entry-edit-submit");
    await flushPromises();

    expect(apiMocks.updatePayrollEntry).toHaveBeenCalledWith("run-1", "entry-1", {
      amount: 18500,
      note: "补发差额定额",
    });
  });

  it("确认批次走确认弹窗并刷新状态；修正入口仅草稿态", async () => {
    mountPage();
    await flushPromises();
    clickButton("run-detail-run-1");
    await flushPromises();

    expect(document.querySelector('[data-testid="run-confirm"]')).toBeTruthy();
    clickButton("run-confirm");
    await flushPromises();

    expect(apiMocks.confirmPayrollRun).toHaveBeenCalledWith("run-1");
    expect(document.querySelector('[data-testid="detail-status-confirmed"]')).toBeTruthy();

    // 确认后修正入口消失（单元格变为纯文本）
    expect(document.querySelector('[data-testid="matrix-cell-emp-1-it-1"]')).toBeNull();
  });

  it("创建与确认按钮随权限显隐", async () => {
    const withPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-create-run"]')).toBeTruthy();
    withPerm.unmount();
    document.body.innerHTML = "";

    permState.granted = new Set(["hr:payroll:read"]);
    const withoutPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-create-run"]')).toBeNull();
    withoutPerm.unmount();
  });

  it("标准代发导出：confirmed 态有权限出项，点击走文件下载并回告", async () => {
    permState.granted = new Set(["hr:payroll:read", "hr:payroll:export"]);
    apiMocks.exportPayrollRun.mockResolvedValue({
      code: 200,
      data: { filename: "标准代发-2026-09.xlsx", content_base64: "AAAA" },
    });
    mountPage();
    await flushPromises();

    clickButton("run-detail-run-2");
    await flushPromises();
    expect(document.querySelector('[data-testid="run-export"]')).toBeTruthy();

    clickButton("run-export");
    await flushPromises();

    expect(apiMocks.exportPayrollRun).toHaveBeenCalledWith("run-2");
    expect(downloadMocks.downloadBase64File).toHaveBeenCalledWith("标准代发-2026-09.xlsx", "AAAA");
    const { notifySuccess } = await import("@/framework/utils/feedback");
    expect(notifySuccess).toHaveBeenCalledWith(expect.stringContaining("已写审计"));
  });

  it("标准代发导出按钮随状态与权限显隐：draft 态或无导出权限不出项", async () => {
    permState.granted = new Set(["hr:payroll:read", "hr:payroll:export"]);
    mountPage();
    await flushPromises();
    clickButton("run-detail-run-1");
    await flushPromises();
    // run-1 为 draft：不满足 confirmed/paid
    expect(document.querySelector('[data-testid="run-export"]')).toBeNull();

    permState.granted = new Set(["hr:payroll:read", "hr:payroll:write", "hr:payroll:confirm"]);
    const wrapper = mountPage();
    await flushPromises();
    clickButton("run-detail-run-2");
    await flushPromises();
    // 有状态无导出权限
    expect(document.querySelector('[data-testid="run-export"]')).toBeNull();
    wrapper.unmount();
  });
});
