/**
 * MergeCandidateModal 组件测试：疑似重复档建议区渲染与直选目标、
 * 手动检索列表互斥排除 source、确认合并调用
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MergeCandidateModal from "@/hr/components/candidate/MergeCandidateModal.vue";
import type { Application, MergeSuggestion } from "@/hr/types/recruiting";

const apiMocks = vi.hoisted(() => ({
  listCandidateCards: vi.fn(),
  mergeCandidates: vi.fn(),
  getMergeSuggestions: vi.fn(),
}));

vi.mock("@/hr/api/candidate", () => ({
  listCandidateCards: apiMocks.listCandidateCards,
  mergeCandidates: apiMocks.mergeCandidates,
  getMergeSuggestions: apiMocks.getMergeSuggestions,
}));

vi.mock("@/framework/utils/feedback", () => ({
  confirmAction: vi.fn(async () => true),
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

const SUGGESTIONS: MergeSuggestion[] = [
  { candidate_id: "cand-2", name: "重名一", phone: "13800001111", email: null, matched_by: "phone" },
  { candidate_id: "cand-3", name: "重名二", phone: null, email: "zhang@example.com", matched_by: "email" },
];

function makeApplication(overrides: Partial<Application> = {}): Application {
  return {
    id: "app-1",
    candidate_id: "cand-1",
    candidate_name: "张三",
    requisition_id: "req-1",
    requisition_title: "后端工程师",
    stage: "pending_screening",
    stage_history: [],
    match_score: null,
    apply_time: "2026-10-10T10:00:00",
    employee_id: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  apiMocks.listCandidateCards.mockResolvedValue({
    code: 200,
    data: [makeApplication(), makeApplication({ id: "app-2", candidate_id: "cand-9", candidate_name: "李四" })],
    total: 2,
  });
  apiMocks.getMergeSuggestions.mockResolvedValue({ code: 200, data: SUGGESTIONS });
  apiMocks.mergeCandidates.mockResolvedValue({ code: 200, data: { merged_applications: 2 } });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("MergeCandidateModal", () => {
  it("打开时拉取疑似重复档建议，渲染命中方式徽标", async () => {
    const wrapper = mount(MergeCandidateModal, {
      props: { open: true, source: { id: "cand-1", name: "张三" } },
      attachTo: document.body,
    });
    await flushPromises();

    expect(apiMocks.getMergeSuggestions).toHaveBeenCalledWith("cand-1");
    const dialog = document.querySelector('[data-testid="merge-candidate-dialog"]');
    expect(dialog?.textContent).toContain("疑似重复档");
    expect(dialog?.querySelector('[data-testid="merge-suggestion-cand-2"]')?.textContent).toContain("手机命中");
    expect(dialog?.querySelector('[data-testid="merge-suggestion-cand-3"]')?.textContent).toContain("邮箱命中");
    wrapper.unmount();
  });

  it("点击建议直选目标，确认合并调 mergeCandidates(source, target)", async () => {
    const wrapper = mount(MergeCandidateModal, {
      props: { open: true, source: { id: "cand-1", name: "张三" } },
      attachTo: document.body,
    });
    await flushPromises();

    (document.querySelector('[data-testid="merge-suggestion-cand-2"]') as HTMLButtonElement).click();
    await flushPromises();

    const submit = document.querySelector('[data-testid="merge-submit"]') as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
    submit.click();
    await flushPromises();

    expect(apiMocks.mergeCandidates).toHaveBeenCalledWith("cand-1", "cand-2");
    wrapper.unmount();
  });

  it("无建议时不渲染建议区，检索列表排除 source 自身", async () => {
    apiMocks.getMergeSuggestions.mockResolvedValue({ code: 200, data: [] });
    const wrapper = mount(MergeCandidateModal, {
      props: { open: true, source: { id: "cand-1", name: "张三" } },
      attachTo: document.body,
    });
    await flushPromises();

    expect(document.querySelector('[data-testid="merge-suggestion-cand-2"]')).toBeNull();
    expect(document.querySelector('[data-testid="merge-target-cand-9"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="merge-target-cand-1"]')).toBeNull();
    wrapper.unmount();
  });
});
