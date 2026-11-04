/**
 * LeaveApplyModal（请假申请）测试：起止时间联动时长只读回显（day 闭区间）、
 * 必填校验拦截、提交载荷正确
 */
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LeaveApplyModal from "@/hr/components/leave/LeaveApplyModal.vue";
import type { LeaveType } from "@/hr/types/leave";

const apiMocks = vi.hoisted(() => ({
  submitMyLeaveRequest: vi.fn(),
}));

vi.mock("@/hr/api/leave", () => ({
  submitMyLeaveRequest: apiMocks.submitMyLeaveRequest,
  listMyLeaveBalances: vi.fn(),
  listMyLeaveRequests: vi.fn(),
  cancelMyLeaveRequest: vi.fn(),
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
  confirmAction: vi.fn(async () => true),
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

function mountModal(): VueWrapper {
  return mount(LeaveApplyModal, {
    props: { open: true, leaveTypes: TYPES },
    attachTo: document.body,
  });
}

function setNativeValue(testid: string, value: string, tag = "input") {
  const host = document.querySelector(`[data-testid="${testid}"]`);
  const input = (host?.querySelector(tag) ?? host) as HTMLInputElement | null;
  if (!input) throw new Error(`element not found: ${testid}`);
  input.value = value;
  input.dispatchEvent(new Event("input"));
}

function clickButton(testid: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  if (el instanceof HTMLElement) el.click();
}

beforeEach(() => {
  vi.resetAllMocks();
  apiMocks.submitMyLeaveRequest.mockResolvedValue({ code: 200, data: null });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("LeaveApplyModal", () => {
  it("选择类型与起止时间后时长只读回显（day 闭区间），完整提交载荷正确", async () => {
    const wrapper = mountModal();
    await flushPromises();

    // Select 经组件实例驱动 v-model（reka 弹层在 jsdom 中不展开）
    const select = wrapper.findComponent({ name: "Select" });
    expect(select.exists()).toBe(true);
    select.vm.$emit("update:modelValue", "lt-1");
    await flushPromises();

    setNativeValue("leave-apply-start-input", "2026-10-20T09:00");
    setNativeValue("leave-apply-end-input", "2026-10-21T18:00");
    await flushPromises();

    const durationHost = document.querySelector('[data-testid="leave-apply-duration"]');
    const durationText = durationHost?.querySelector("input")?.value ?? durationHost?.textContent ?? "";
    expect(durationText).toContain("2");
    expect(durationText).toContain("天");

    setNativeValue("leave-apply-reason", "家中事务", "textarea");
    await flushPromises();

    clickButton("leave-apply-submit");
    await flushPromises();

    expect(apiMocks.submitMyLeaveRequest).toHaveBeenCalledWith({
      leave_type_id: "lt-1",
      start_time: "2026-10-20T09:00",
      end_time: "2026-10-21T18:00",
      reason: "家中事务",
    });
    expect(wrapper.emitted("saved")).toHaveLength(1);
    wrapper.unmount();
  });

  it("未选类型或事由为空时提交被拦截", async () => {
    const wrapper = mountModal();
    await flushPromises();

    clickButton("leave-apply-submit");
    await flushPromises();
    expect(apiMocks.submitMyLeaveRequest).not.toHaveBeenCalled();

    const select = wrapper.findComponent({ name: "Select" });
    select.vm.$emit("update:modelValue", "lt-1");
    await flushPromises();

    setNativeValue("leave-apply-start-input", "2026-10-20T09:00");
    setNativeValue("leave-apply-end-input", "2026-10-21T18:00");
    await flushPromises();

    clickButton("leave-apply-submit");
    await flushPromises();
    expect(apiMocks.submitMyLeaveRequest).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
