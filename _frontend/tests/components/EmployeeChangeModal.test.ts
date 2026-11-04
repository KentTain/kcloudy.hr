/**
 * EmployeeChangeModal 单元测试：异动提交载荷（转正/离职直达）
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import EmployeeChangeModal from "@/hr/components/employee/EmployeeChangeModal.vue";
import type { Employee } from "@/hr/types/employee";

const apiMocks = vi.hoisted(() => ({
  createChange: vi.fn(),
  getPositionOptions: vi.fn(),
  listSalaryItemOptions: vi.fn(),
}));

vi.mock("@/hr/api/employee", () => ({
  createChange: apiMocks.createChange,
}));

vi.mock("@/hr/api/reference", () => ({
  getPositionOptions: apiMocks.getPositionOptions,
  listSalaryItemOptions: apiMocks.listSalaryItemOptions,
}));

vi.mock("@/framework/utils/feedback", () => ({
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

const EMPLOYEE: Employee = {
  id: "emp-1",
  employee_no: "EMP001",
  name: "张三",
  gender: "male",
  phone: null,
  work_email: null,
  org_id: "org-1",
  position_id: null,
  job_level: "P4",
  status: "probation",
  hire_date: "2025-01-01",
  regular_date: null,
  offboard_date: null,
  user_id: null,
  has_account: true,
};

function mountModal(props: Record<string, unknown>) {
  return mount(EmployeeChangeModal, {
    props: { open: true, employee: EMPLOYEE, ...props, "onUpdate:open": vi.fn(), onSaved: vi.fn() },
    attachTo: document.body,
  });
}

function clickButton(testid: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  expect(el, `missing ${testid}`).toBeTruthy();
  (el as HTMLButtonElement).click();
}

beforeEach(() => {
  vi.resetAllMocks();
  apiMocks.createChange.mockResolvedValue({ code: 200, data: {} });
  apiMocks.getPositionOptions.mockRejectedValue(new Error("no perm"));
  apiMocks.listSalaryItemOptions.mockRejectedValue(new Error("no perm"));
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("EmployeeChangeModal", () => {
  it("默认转正：提交带 employee_id 与今天生效日期", async () => {
    mountModal({});
    await flushPromises();

    clickButton("change-submit");
    await flushPromises();

    expect(apiMocks.createChange).toHaveBeenCalledTimes(1);
    const payload = apiMocks.createChange.mock.calls[0][0];
    expect(payload.employee_id).toBe("emp-1");
    expect(payload.change_type).toBe("probate");
    expect(payload.effective_date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("initialType=offboard 直达离职类型", async () => {
    mountModal({ initialType: "offboard" });
    await flushPromises();

    clickButton("change-submit");
    await flushPromises();

    const payload = apiMocks.createChange.mock.calls[0][0];
    expect(payload.change_type).toBe("offboard");
  });

  it("岗位选项接口失败时降级不阻断提交", async () => {
    mountModal({});
    await flushPromises();

    clickButton("change-submit");
    await flushPromises();

    expect(apiMocks.createChange).toHaveBeenCalled();
  });
});
