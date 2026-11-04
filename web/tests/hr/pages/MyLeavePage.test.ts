/**
 * MyLeavePage（console 我的假期）页面测试：余额卡区渲染（从余额派生申请类型）、
 * 请假单列表与待审批撤销、状态筛选查询参数
 */
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MyLeavePage from "@/hr/pages/my-leave/MyLeavePage.vue";
import type { LeaveBalance, LeaveRequest } from "@/hr/types/leave";

const confirmState = vi.hoisted(() => ({ result: true }));

const apiMocks = vi.hoisted(() => ({
  listMyLeaveBalances: vi.fn(),
  listMyLeaveRequests: vi.fn(),
  cancelMyLeaveRequest: vi.fn(),
  submitMyLeaveRequest: vi.fn(),
}));

vi.mock("@/hr/api/leave", () => ({
  listMyLeaveBalances: apiMocks.listMyLeaveBalances,
  listMyLeaveRequests: apiMocks.listMyLeaveRequests,
  cancelMyLeaveRequest: apiMocks.cancelMyLeaveRequest,
  submitMyLeaveRequest: apiMocks.submitMyLeaveRequest,
  listLeaveTypes: vi.fn(),
  updateLeaveType: vi.fn(),
  deleteLeaveType: vi.fn(),
  listLeaveRequests: vi.fn(),
  approveLeaveRequest: vi.fn(),
  rejectLeaveRequest: vi.fn(),
  listLeaveBalances: vi.fn(),
  adjustLeaveBalance: vi.fn(),
}));

vi.mock("@/framework/utils/feedback", () => ({
  confirmAction: vi.fn(async () => confirmState.result),
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

const BALANCES: LeaveBalance[] = [
  {
    id: "lb-1",
    employee_id: "emp-me",
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
  {
    id: "lb-2",
    employee_id: "emp-me",
    employee_no: "EMP001",
    employee_name: "张三",
    org_id: "org-1",
    leave_type_id: "lt-2",
    leave_type_code: "personal_leave",
    leave_type_name: "事假",
    unit: "hour",
    year: 2026,
    total_quota: 24,
    used: 4,
    frozen: 0,
    balance: 20,
  },
];

const REQUESTS: LeaveRequest[] = [
  {
    id: "lr-1",
    employee_id: "emp-me",
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
  {
    id: "lr-2",
    employee_id: "emp-me",
    employee_no: "EMP001",
    employee_name: "张三",
    org_id: "org-1",
    leave_type_id: "lt-2",
    leave_type_code: "personal_leave",
    leave_type_name: "事假",
    unit: "hour",
    start_time: "2026-10-10T09:00",
    end_time: "2026-10-10T12:00",
    duration: 3,
    reason: "外出办事",
    attachment_file: null,
    status: "approved",
    approver_id: "approver-1",
    approve_comment: "同意",
    approved_at: "2026-10-10T08:00:00",
    created_at: "2026-10-09T10:00:00",
  },
];

function mountPage(): VueWrapper {
  return mount(MyLeavePage, { attachTo: document.body });
}

function clickButton(testid: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  if (el instanceof HTMLElement) el.click();
}

beforeEach(() => {
  vi.resetAllMocks();
  confirmState.result = true;
  apiMocks.listMyLeaveBalances.mockResolvedValue({ code: 200, data: BALANCES });
  apiMocks.listMyLeaveRequests.mockResolvedValue({
    code: 200,
    data: REQUESTS,
    total: 2,
    page: 1,
    page_size: 10,
  });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("MyLeavePage", () => {
  it("余额卡区按类型渲染可用余额与额度明细", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(apiMocks.listMyLeaveBalances).toHaveBeenCalledTimes(1);
    const cards = document.querySelector('[data-testid="my-leave-balance-cards"]')?.textContent ?? "";
    expect(cards).toContain("年假");
    expect(cards).toContain("事假");
    expect(document.querySelector('[data-testid="my-leave-balance-lb-1"]')?.textContent).toContain("2");
    wrapper.unmount();
  });

  it("请假单列表渲染，仅待审批行出撤销按钮，撤销确认后调接口并刷新余额", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(apiMocks.listMyLeaveRequests).toHaveBeenCalledTimes(1);
    expect(document.body.textContent ?? "").toContain("家中事务");
    expect(document.querySelector('[data-testid="my-leave-cancel-lr-1"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="my-leave-cancel-lr-2"]')).toBeNull();

    apiMocks.cancelMyLeaveRequest.mockResolvedValue({ code: 200, data: null });
    clickButton("my-leave-cancel-lr-1");
    await flushPromises();

    expect(apiMocks.cancelMyLeaveRequest).toHaveBeenCalledWith("lr-1");
    expect(apiMocks.listMyLeaveBalances).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("撤销确认取消时不调接口", async () => {
    const wrapper = mountPage();
    await flushPromises();

    confirmState.result = false;
    clickButton("my-leave-cancel-lr-1");
    await flushPromises();

    expect(apiMocks.cancelMyLeaveRequest).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("状态筛选查询按钮联动查询参数", async () => {
    const wrapper = mountPage();
    await flushPromises();

    // Select 渲染在 reka 弹层中，直接驱动查询按钮验证默认参数（全部状态不下发）
    clickButton("my-leave-search");
    await flushPromises();

    expect(apiMocks.listMyLeaveRequests).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: undefined, page: 1, page_size: 10 }),
    );
    wrapper.unmount();
  });
});
