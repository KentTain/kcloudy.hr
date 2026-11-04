/**
 * EmployeeFormModal 单元测试：create 分步流（姓名/入职日期校验 + 提交载荷）
 * 与 edit 单表单（掩码证件未变不下发）
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import EmployeeFormModal from "@/hr/components/employee/EmployeeFormModal.vue";
import type { EmployeeDetail } from "@/hr/types/employee";

const apiMocks = vi.hoisted(() => ({
  createEmployee: vi.fn(),
  updateEmployee: vi.fn(),
  listFieldGroups: vi.fn(),
  listFieldDefinitions: vi.fn(),
  getPositionOptions: vi.fn(),
}));

vi.mock("@/hr/api/employee", () => ({
  createEmployee: apiMocks.createEmployee,
  updateEmployee: apiMocks.updateEmployee,
}));

vi.mock("@/hr/api/field", () => ({
  listFieldGroups: apiMocks.listFieldGroups,
  listFieldDefinitions: apiMocks.listFieldDefinitions,
}));

vi.mock("@/hr/api/reference", () => ({
  getPositionOptions: apiMocks.getPositionOptions,
}));

vi.mock("@/framework/utils/feedback", () => ({
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

function setInputValue(testid: string, value: string) {
  const el = document.querySelector(`[data-testid="${testid}"] input`) ?? document.querySelector(`[data-testid="${testid}"]`);
  expect(el, `missing ${testid}`).toBeTruthy();
  const input = el as HTMLInputElement;
  input.value = value;
  input.dispatchEvent(new Event("input"));
}

/** DateInput 是 Popover+readonly 输入，无法直填——stub 成可输入的原生 input */
const DateInputStub = {
  props: ["modelValue", "placeholder"],
  emits: ["update:modelValue"],
  template:
    '<input class="dateinput-stub" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
};

function clickButton(testid: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  expect(el, `missing button ${testid}`).toBeTruthy();
  (el as HTMLButtonElement).click();
}

function mountModal(props: Record<string, unknown>) {
  return mount(EmployeeFormModal, {
    props: { open: true, ...props, "onUpdate:open": vi.fn(), onSaved: vi.fn() },
    global: { stubs: { DateInput: DateInputStub } },
    attachTo: document.body,
  });
}

const EDIT_EMPLOYEE: EmployeeDetail = {
  id: "emp-1",
  employee_no: "EMP001",
  name: "张三",
  gender: "male",
  phone: "13800000000",
  work_email: null,
  org_id: null,
  position_id: null,
  job_level: "P5",
  status: "regular",
  hire_date: "2025-01-01",
  regular_date: null,
  offboard_date: null,
  user_id: null,
  has_account: true,
  birth_date: "1995-01-01",
  id_card_masked: "110101********1234",
  bank_card_masked: null,
};

beforeEach(() => {
  vi.resetAllMocks();
  apiMocks.listFieldGroups.mockResolvedValue({ code: 200, data: [] });
  apiMocks.listFieldDefinitions.mockResolvedValue({ code: 200, data: [] });
  apiMocks.getPositionOptions.mockResolvedValue({ code: 200, data: [] });
  apiMocks.createEmployee.mockResolvedValue({ code: 200, data: { id: "new-1" } });
  apiMocks.updateEmployee.mockResolvedValue({ code: 200, data: { id: "emp-1" } });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("EmployeeFormModal", () => {
  it("create 分步流：姓名缺失拦截在第一步", async () => {
    mountModal({ mode: "create", employee: null });
    await flushPromises();

    clickButton("employee-form-submit");
    await flushPromises();

    const { notifyError } = await import("@/framework/utils/feedback");
    expect(notifyError).toHaveBeenCalled();
    // 仍在第一步（未出现入职日期必填拦截后直接提交）
    expect(apiMocks.createEmployee).not.toHaveBeenCalled();
  });

  it("create 分步流：第二步校验入职日期后提交载荷", async () => {
    mountModal({ mode: "create", employee: null });
    await flushPromises();

    setInputValue("employee-name-input", "李四");
    setInputValue("employee-hire-date-input", "2026-05-01");
    // 第一步提交 → 进入第二步
    clickButton("employee-form-submit");
    await flushPromises();
    // 第二步提交 → 进入第三步（扩展属性）
    clickButton("employee-form-submit");
    await flushPromises();
    // 第三步提交 → 建档
    clickButton("employee-form-submit");
    await flushPromises();

    expect(apiMocks.createEmployee).toHaveBeenCalledTimes(1);
    const payload = apiMocks.createEmployee.mock.calls[0][0];
    expect(payload.name).toBe("李四");
    expect(payload.hire_date).toBe("2026-05-01");
  });

  it("edit 单表单：掩码证件未变更时不下发 id_card", async () => {
    mountModal({ mode: "edit", employee: EDIT_EMPLOYEE });
    await flushPromises();

    clickButton("employee-form-submit");
    await flushPromises();

    expect(apiMocks.updateEmployee).toHaveBeenCalledTimes(1);
    const [id, payload] = apiMocks.updateEmployee.mock.calls[0];
    expect(id).toBe("emp-1");
    expect(payload.name).toBe("张三");
    expect(payload.id_card).toBeUndefined();
  });
});
