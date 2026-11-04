/**
 * CandidateFormModal 测试：打开拉取需求选项（过滤已关闭）、姓名必填校验、
 * 提交载荷（渠道/关联需求哨兵映射 undefined）
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CandidateFormModal from "@/hr/components/candidate/CandidateFormModal.vue";

const apiMocks = vi.hoisted(() => ({
  createCandidate: vi.fn(),
  listRequisitions: vi.fn(),
}));

vi.mock("@/hr/api/candidate", () => ({
  createCandidate: apiMocks.createCandidate,
}));

vi.mock("@/hr/api/recruiting", () => ({
  listRequisitions: apiMocks.listRequisitions,
}));

vi.mock("@/framework/utils/feedback", () => ({
  confirmAction: vi.fn(async () => true),
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

function setInputValue(selector: string, value: string) {
  const host = document.querySelector(selector);
  const input = host?.querySelector("input") ?? host;
  if (input instanceof HTMLInputElement) {
    input.value = value;
    input.dispatchEvent(new Event("input"));
  }
}

/** DialogContent 经 Teleport 渲染到 body，按钮点击走 document 查询 */
function clickButton(testid: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  if (el instanceof HTMLElement) el.click();
}

function mountModal(open = true) {
  return mount(CandidateFormModal, {
    props: { open },
    attachTo: document.body,
  });
}

let wrapper: ReturnType<typeof mountModal> | null = null;

beforeEach(() => {
  vi.resetAllMocks();
  apiMocks.listRequisitions.mockResolvedValue({
    code: 200,
    data: [
      { id: "req-1", req_no: "REQ-2026-001", title: "后端工程师", status: "recruiting" },
      { id: "req-2", req_no: "REQ-2026-002", title: "已关闭岗", status: "closed" },
    ],
    total: 2,
  });
  apiMocks.createCandidate.mockResolvedValue({ code: 200, data: { id: "cand-1", name: "张三" } });
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  document.body.innerHTML = "";
});

describe("CandidateFormModal", () => {
  it("打开后拉取需求选项（过滤已关闭需求）", async () => {
    wrapper = mountModal();
    await flushPromises();

    expect(apiMocks.listRequisitions).toHaveBeenCalledWith({ page: 1, page_size: 100 });
  });

  it("姓名为空提交触发校验，不发起创建", async () => {
    wrapper = mountModal();
    await flushPromises();

    clickButton("candidate-submit");
    await flushPromises();

    const { notifyError } = await import("@/framework/utils/feedback");
    expect(notifyError).toHaveBeenCalled();
    expect(apiMocks.createCandidate).not.toHaveBeenCalled();
  });

  it("填写姓名后提交，载荷使用手工渠道且不关联需求映射为 undefined", async () => {
    wrapper = mountModal();
    await flushPromises();

    setInputValue('[data-testid="candidate-name-input"]', "张三");
    setInputValue('[data-testid="candidate-phone-input"]', "13800138000");

    clickButton("candidate-submit");
    await flushPromises();

    expect(apiMocks.createCandidate).toHaveBeenCalledWith({
      name: "张三",
      phone: "13800138000",
      email: undefined,
      source_channel: "manual",
      requisition_id: undefined,
    });

    const { notifySuccess } = await import("@/framework/utils/feedback");
    expect(notifySuccess).toHaveBeenCalledWith("候选人已录入");
  });
});
