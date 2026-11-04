/**
 * RequisitionFormModal 三步创建弹窗单元测试：步进校验拦截、提交载荷（渠道默认站内）
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RequisitionFormModal from "@/hr/components/recruiting/RequisitionFormModal.vue";

const apiMocks = vi.hoisted(() => ({
  createRequisition: vi.fn(),
  listChannels: vi.fn(),
  getPositionOptions: vi.fn(),
}));

vi.mock("@/hr/api/recruiting", () => ({
  createRequisition: apiMocks.createRequisition,
  listChannels: apiMocks.listChannels,
}));

vi.mock("@/hr/api/reference", () => ({
  getPositionOptions: apiMocks.getPositionOptions,
}));

vi.mock("@/framework/utils/feedback", () => ({
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

/** OrganizationSelect 是 Popover 树选——stub 成可输入的原生 input（输入值即选组织） */
const OrganizationSelectStub = {
  props: ["modelValue", "multiple", "placeholder"],
  emits: ["update:modelValue"],
  template:
    '<input class="org-select-stub" :value="(modelValue || []).join(\',\')" @input="$emit(\'update:modelValue\', [$event.target.value])" />',
};

function setInputValue(selector: string, value: string) {
  // common Input 的 data-testid 落根 div，先试内层原生 input
  const el =
    (document.querySelector(`${selector} input`) as HTMLInputElement | null) ??
    (document.querySelector(selector) as HTMLInputElement | null);
  expect(el, `missing ${selector}`).toBeTruthy();
  el!.value = value;
  el!.dispatchEvent(new Event("input"));
}

function clickButton(testid: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  expect(el, `missing button ${testid}`).toBeTruthy();
  (el as HTMLButtonElement).click();
}

function mountModal() {
  return mount(RequisitionFormModal, {
    props: { open: true, "onUpdate:open": vi.fn(), onSaved: vi.fn() },
    global: { stubs: { OrganizationSelect: OrganizationSelectStub } },
    attachTo: document.body,
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  apiMocks.listChannels.mockResolvedValue({ code: 200, data: [] });
  apiMocks.getPositionOptions.mockResolvedValue({
    code: 200,
    data: [{ id: "pos-1", name: "后端工程师", code: "BE", job_level: "P5", status: "active" }],
  });
  apiMocks.createRequisition.mockResolvedValue({ code: 200, data: { id: "req-1" } });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("RequisitionFormModal", () => {
  it("第一步缺职位名/部门时拦截（不进入下一步、不提交）", async () => {
    mountModal();
    await flushPromises();

    clickButton("req-step-next");
    await flushPromises();

    const { notifyError } = await import("@/framework/utils/feedback");
    expect(notifyError).toHaveBeenCalled();
    expect(apiMocks.createRequisition).not.toHaveBeenCalled();
    // 仍在第一步（招聘人数输入框可见）
    expect(document.querySelector('[data-testid="req-headcount-input"]')).toBeTruthy();
  });

  it("三步走完后提交载荷：默认站内渠道、人数转数字、可选字段留空不下发", async () => {
    mountModal();
    await flushPromises();

    // Step1 岗位信息
    setInputValue('[data-testid="req-title-input"]', "后端工程师（支付方向）");
    setInputValue(".org-select-stub", "org-1");
    setInputValue('[data-testid="req-headcount-input"]', "3");
    clickButton("req-step-next");
    await flushPromises();

    // Step2 任职要求
    setInputValue('[data-testid="req-job-level-input"]', "P6");
    clickButton("req-step-next");
    await flushPromises();

    // Step3 预算渠道（站内默认勾选，薪酬留空）
    clickButton("req-submit");
    await flushPromises();

    expect(apiMocks.createRequisition).toHaveBeenCalledTimes(1);
    const payload = apiMocks.createRequisition.mock.calls[0][0];
    expect(payload.title).toBe("后端工程师（支付方向）");
    expect(payload.org_id).toBe("org-1");
    expect(payload.headcount).toBe(3);
    expect(payload.job_level).toBe("P6");
    expect(payload.priority).toBe("medium");
    expect(payload.channels).toEqual(["internal"]);
    expect(payload.salary_min).toBeUndefined();
    expect(payload.salary_max).toBeUndefined();
  });

  it("第三步薪酬下限高于上限时拦截提交", async () => {
    mountModal();
    await flushPromises();

    setInputValue('[data-testid="req-title-input"]', "测试工程师");
    setInputValue(".org-select-stub", "org-1");
    clickButton("req-step-next");
    await flushPromises();
    clickButton("req-step-next");
    await flushPromises();

    setInputValue('[data-testid="req-salary-min-input"]', "30");
    setInputValue('[data-testid="req-salary-max-input"]', "20");
    clickButton("req-submit");
    await flushPromises();

    const { notifyError } = await import("@/framework/utils/feedback");
    expect(notifyError).toHaveBeenCalled();
    expect(apiMocks.createRequisition).not.toHaveBeenCalled();
  });
});
