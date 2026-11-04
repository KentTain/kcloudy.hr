/**
 * LeavePage 页面测试：三页签（假期类型/请假单/假期余额）切换加载、
 * 请假单状态筛选参数、审批弹窗通过与驳回必填、假期类型删除保护
 */
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LeavePage from "@/hr/pages/leave/LeavePage.vue";
import type { LeaveBalance, LeaveRequest, LeaveType } from "@/hr/types/leave";

const permState = vi.hoisted(() => ({
  granted: new Set<string>([
    "hr:leave:read",
    "hr:leave:write",
    "hr:leave:approve",
    "hr:leave:transfer",
  ]),
}));

const confirmState = vi.hoisted(() => ({ result: true }));

const apiMocks = vi.hoisted(() => ({
  listLeaveTypes: vi.fn(),
  updateLeaveType: vi.fn(),
  deleteLeaveType: vi.fn(),
  listLeaveRequests: vi.fn(),
  approveLeaveRequest: vi.fn(),
  rejectLeaveRequest: vi.fn(),
  transferLeaveRequest: vi.fn(),
  listLeaveBalances: vi.fn(),
  adjustLeaveBalance: vi.fn(),
  getOrgTree: vi.fn(),
}));

vi.mock("@/hr/api/leave", () => ({
  listLeaveTypes: apiMocks.listLeaveTypes,
  updateLeaveType: apiMocks.updateLeaveType,
  deleteLeaveType: apiMocks.deleteLeaveType,
  listLeaveRequests: apiMocks.listLeaveRequests,
  approveLeaveRequest: apiMocks.approveLeaveRequest,
  rejectLeaveRequest: apiMocks.rejectLeaveRequest,
  transferLeaveRequest: apiMocks.transferLeaveRequest,
  listLeaveBalances: apiMocks.listLeaveBalances,
  adjustLeaveBalance: apiMocks.adjustLeaveBalance,
}));

vi.mock("@/hr/api/reference", () => ({
  getOrgTree: apiMocks.getOrgTree,
  getPositionOptions: vi.fn(),
  listEmployeeSalaryPackages: vi.fn(),
  getBandComparison: vi.fn(),
  listSalaryItemOptions: vi.fn(),
}));

vi.mock("@/framework/stores", () => ({
  useUserStore: () => ({
    hasPermission: (code: string) => permState.granted.has(code),
  }),
}));

vi.mock("@/framework/utils/feedback", () => ({
  confirmAction: vi.fn(async () => confirmState.result),
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

const TYPES: LeaveType[] = [
  {
    id: "lt-1",
    code: "annual_leave",
    name: "年假",
    unit: "day",
    paid: true,
    quota_rule: "annual_fixed",
    default_quota: 5,
    status: "enabled",
  },
];

const REQUESTS: LeaveRequest[] = [
  {
    id: "lr-1",
    employee_id: "emp-1",
    employee_no: "EMP001",
    employee_name: "张三",
    org_id: "org-1",
    leave_type_id: "lt-1",
    leave_type_code: "annual_leave",
    leave_type_name: "年假",
    unit: "day",
    start_time: "2026-10-20T09:00",
    end_time: "2026-10-21T18:00",
    duration: 2,
    reason: "家中事务",
    attachment_file: null,
    status: "pending",
    approver_id: null,
    approve_comment: null,
    approved_at: null,
    created_at: "2026-10-17T10:00:00",
  },
];

const BALANCES: LeaveBalance[] = [
  {
    id: "lb-1",
    employee_id: "emp-1",
    employee_no: "EMP001",
    employee_name: "张三",
    org_id: "org-1",
    leave_type_id: "lt-1",
    leave_type_code: "annual_leave",
    leave_type_name: "年假",
    unit: "day",
    year: 2026,
    total_quota: 5,
    used: 1,
    frozen: 2,
    balance: 2,
  },
];

function mountPage(): VueWrapper {
  return mount(LeavePage, {
    attachTo: document.body,
    global: { stubs: { PeopleSelectDialog: true } },
  });
}

function clickButton(testid: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  if (el instanceof HTMLElement) el.click();
}

function switchTab(testid: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  el?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
}

beforeEach(() => {
  vi.resetAllMocks();
  confirmState.result = true;
  permState.granted = new Set([
    "hr:leave:read",
    "hr:leave:write",
    "hr:leave:approve",
    "hr:leave:transfer",
  ]);
  apiMocks.transferLeaveRequest.mockResolvedValue({ code: 200, data: null });
  apiMocks.listLeaveTypes.mockResolvedValue({
    code: 200,
    data: TYPES,
    total: 1,
    page: 1,
    page_size: 20,
  });
  apiMocks.listLeaveRequests.mockResolvedValue({
    code: 200,
    data: REQUESTS,
    total: 1,
    page: 1,
    page_size: 20,
  });
  apiMocks.listLeaveBalances.mockResolvedValue({
    code: 200,
    data: BALANCES,
    total: 1,
    page: 1,
    page_size: 20,
  });
  apiMocks.getOrgTree.mockResolvedValue({
    code: 200,
    data: [{ id: "org-1", name: "研发部", children: [] }],
  });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("LeavePage", () => {
  it("默认页签渲染假期类型列表（单位/额度规则/状态），类型参照加载两次", async () => {
    const wrapper = mountPage();
    await flushPromises();

    // loadLeaveTypes（参照）+ typeDataTable 首次拉取
    expect(apiMocks.listLeaveTypes).toHaveBeenCalled();
    const body = document.body.textContent ?? "";
    expect(body).toContain("annual_leave");
    expect(body).toContain("年假");
    expect(body).toContain("按年度固定额度");
    wrapper.unmount();
  });

  it("切到请假单页签加载列表，待审批行出审批按钮，筛选联动查询参数", async () => {
    const wrapper = mountPage();
    await flushPromises();
    expect(apiMocks.listLeaveRequests).not.toHaveBeenCalled();

    switchTab("leave-tab-requests");
    await flushPromises();

    expect(apiMocks.listLeaveRequests).toHaveBeenCalled();
    expect(document.body.textContent ?? "").toContain("张三");
    expect(document.querySelector('[data-testid="leave-approve-lr-1"]')).toBeTruthy();

    clickButton("leave-req-search");
    await flushPromises();
    expect(apiMocks.listLeaveRequests).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: undefined, keyword: undefined })
    );
    wrapper.unmount();
  });

  it("审批弹窗：驳回不填意见被拦截，填写后调驳回接口并刷新", async () => {
    const wrapper = mountPage();
    await flushPromises();

    switchTab("leave-tab-requests");
    await flushPromises();

    clickButton("leave-approve-lr-1");
    await flushPromises();

    const dialog = document.querySelector('[data-testid="leave-approve-dialog"]');
    expect(dialog).toBeTruthy();
    expect(dialog?.textContent ?? "").toContain("张三");
    expect(
      document.querySelector('[data-testid="leave-approve-summary"]')?.textContent ?? ""
    ).toContain("家中事务");

    // 驳回必填：空意见点击驳回不调接口
    clickButton("leave-approve-reject");
    await flushPromises();
    expect(apiMocks.rejectLeaveRequest).not.toHaveBeenCalled();

    const commentHost = document.querySelector('[data-testid="leave-approve-comment"]');
    const commentInput = (commentHost?.querySelector("textarea") ??
      commentHost) as HTMLTextAreaElement | null;
    if (commentInput) {
      commentInput.value = "项目排期冲突";
      commentInput.dispatchEvent(new Event("input"));
    }
    await flushPromises();

    apiMocks.rejectLeaveRequest.mockResolvedValue({ code: 200, data: null });
    clickButton("leave-approve-reject");
    await flushPromises();

    expect(apiMocks.rejectLeaveRequest).toHaveBeenCalledWith("lr-1", "项目排期冲突");
    wrapper.unmount();
  });

  it("审批弹窗通过按钮调用 approve 接口", async () => {
    const wrapper = mountPage();
    await flushPromises();

    switchTab("leave-tab-requests");
    await flushPromises();

    clickButton("leave-approve-lr-1");
    await flushPromises();

    apiMocks.approveLeaveRequest.mockResolvedValue({ code: 200, data: null });
    clickButton("leave-approve-approve");
    await flushPromises();

    expect(apiMocks.approveLeaveRequest).toHaveBeenCalledWith("lr-1");
    wrapper.unmount();
  });

  it("切到假期余额页签按当年加载，调整弹窗提交新总额度", async () => {
    const wrapper = mountPage();
    await flushPromises();

    switchTab("leave-tab-balances");
    await flushPromises();

    expect(apiMocks.listLeaveBalances).toHaveBeenCalled();
    expect(apiMocks.listLeaveBalances).toHaveBeenLastCalledWith(
      expect.objectContaining({ year: new Date().getFullYear() })
    );
    expect(document.querySelector('[data-testid="leave-balance-adjust-lb-1"]')).toBeTruthy();

    clickButton("leave-balance-adjust-lb-1");
    await flushPromises();

    const dialog = document.querySelector('[data-testid="leave-balance-adjust-dialog"]');
    expect(dialog).toBeTruthy();

    const quotaHost = document.querySelector('[data-testid="leave-balance-adjust-quota-input"]');
    const quotaInput = (quotaHost?.querySelector("input") ?? quotaHost) as HTMLInputElement | null;
    if (quotaInput) {
      quotaInput.value = "10";
      quotaInput.dispatchEvent(new Event("input"));
    }
    await flushPromises();

    apiMocks.adjustLeaveBalance.mockResolvedValue({ code: 200, data: null });
    clickButton("leave-balance-adjust-submit");
    await flushPromises();

    expect(apiMocks.adjustLeaveBalance).toHaveBeenCalledWith("lb-1", 10);
    wrapper.unmount();
  });

  it("删除类型走确认弹窗并调删除接口，权限缺失时操作列不出按钮", async () => {
    const wrapper = mountPage();
    await flushPromises();

    apiMocks.deleteLeaveType.mockResolvedValue({ code: 200, data: null });
    clickButton("leave-type-delete-annual_leave");
    await flushPromises();

    expect(apiMocks.deleteLeaveType).toHaveBeenCalledWith("lt-1");
    wrapper.unmount();
    document.body.innerHTML = "";

    permState.granted = new Set(["hr:leave:read"]);
    const readonly = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="leave-type-delete-annual_leave"]')).toBeNull();
    expect(document.querySelector('[data-testid="open-leave-type-form"]')).toBeNull();
    readonly.unmount();
  });

  it("待审批行出移交按钮（随权限显隐），选择人员确认后调移交接口并刷新", async () => {
    const wrapper = mountPage();
    await flushPromises();
    switchTab("leave-tab-requests");
    await flushPromises();

    const transferBtn = document.querySelector(
      '[data-testid="leave-transfer-lr-1"]'
    ) as HTMLElement | null;
    expect(transferBtn).toBeTruthy();
    transferBtn!.click();
    await flushPromises();

    const dialog = wrapper.findComponent({ name: "PeopleSelectDialog" });
    expect(dialog.exists()).toBe(true);
    expect(dialog.props("open")).toBe(true);

    dialog.vm.$emit(
      "confirm",
      ["u-2"],
      [{ id: "u-2", username: "lisi", nickname: "李四", status: "active" }]
    );
    await flushPromises();

    expect(apiMocks.transferLeaveRequest).toHaveBeenCalledWith("lr-1", "u-2");
    expect(apiMocks.listLeaveRequests).toHaveBeenCalledTimes(2);
    wrapper.unmount();
    document.body.innerHTML = "";

    permState.granted = new Set(["hr:leave:read", "hr:leave:approve"]);
    const noPerm = mountPage();
    await flushPromises();
    switchTab("leave-tab-requests");
    await flushPromises();
    expect(document.querySelector('[data-testid="leave-transfer-lr-1"]')).toBeNull();
    noPerm.unmount();
  });
});
