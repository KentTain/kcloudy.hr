/**
 * InterviewReviewModal（面试评价弹窗）测试：AI 纪要任务化提交 → 轮询面试详情
 * 直至纪要回写展示；AI 追问建议列表展示与点击插入反馈框
 */
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import InterviewReviewModal from "@/hr/components/interview/InterviewReviewModal.vue";
import type { InterviewDayItem } from "@/hr/types/recruiting";

const apiMocks = vi.hoisted(() => ({
  submitInterviewSummary: vi.fn(),
  getInterviewDetail: vi.fn(),
  getFollowupQuestions: vi.fn(),
  updateInterview: vi.fn(),
}));

vi.mock("@/hr/api/interview", () => ({
  submitInterviewSummary: apiMocks.submitInterviewSummary,
  getInterviewDetail: apiMocks.getInterviewDetail,
  getFollowupQuestions: apiMocks.getFollowupQuestions,
  updateInterview: apiMocks.updateInterview,
  createInterview: vi.fn(),
  getWeeklyInterviews: vi.fn(),
}));

vi.mock("@/framework/utils/feedback", () => ({
  confirmAction: vi.fn(async () => true),
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

function makeInterview(): InterviewDayItem {
  return {
    id: "itv-1",
    application_id: "app-1",
    candidate_name: "张三",
    requisition_title: "Python 工程师",
    round: 2,
    interviewer_id: "emp-1",
    scheduled_at: "2026-10-18T09:00:00",
    interview_form: "onsite",
    result: "pending",
  };
}

function mountModal(): VueWrapper {
  return mount(InterviewReviewModal, {
    props: { open: true, interview: makeInterview() },
    attachTo: document.body,
  });
}

function clickButton(testid: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  if (el instanceof HTMLElement) el.click();
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("InterviewReviewModal", () => {
  it("纪要任务提交后轮询详情，就绪后展示纪要", async () => {
    apiMocks.submitInterviewSummary.mockResolvedValue({
      code: 200,
      data: { task_id: "task-9", duplicated: false },
    });
    apiMocks.getInterviewDetail
      .mockResolvedValueOnce({ code: 200, data: { id: "itv-1", ai_summary: null } })
      .mockResolvedValueOnce({ code: 200, data: { id: "itv-1", ai_summary: "纪要：表达清晰" } });

    const wrapper = mountModal();
    await flushPromises();

    clickButton("interview-review-ai-summary");
    await flushPromises();
    expect(apiMocks.submitInterviewSummary).toHaveBeenCalledWith("itv-1");
    expect(document.querySelector('[data-testid="interview-review-summary-pending"]')).not.toBeNull();

    await vi.advanceTimersByTimeAsync(2000);
    await flushPromises();
    expect(apiMocks.getInterviewDetail).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(2000);
    await flushPromises();
    expect(apiMocks.getInterviewDetail).toHaveBeenCalledTimes(2);
    expect(
      document.querySelector('[data-testid="interview-review-summary-text"]')?.textContent,
    ).toContain("纪要：表达清晰");
    expect(document.querySelector('[data-testid="interview-review-summary-pending"]')).toBeNull();
    wrapper.unmount();
  });

  it("重复提交返回既有 task_id 不重复排队，仍继续轮询", async () => {
    apiMocks.submitInterviewSummary.mockResolvedValue({
      code: 200,
      data: { task_id: "task-existing", duplicated: true },
    });
    apiMocks.getInterviewDetail.mockResolvedValue({
      code: 200,
      data: { id: "itv-1", ai_summary: "纪要已回写" },
    });

    const wrapper = mountModal();
    await flushPromises();

    clickButton("interview-review-ai-summary");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(2000);
    await flushPromises();

    expect(apiMocks.submitInterviewSummary).toHaveBeenCalledTimes(1);
    expect(
      document.querySelector('[data-testid="interview-review-summary-text"]')?.textContent,
    ).toContain("纪要已回写");
    wrapper.unmount();
  });

  it("AI 追问建议展示列表，点击问题插入反馈框", async () => {
    apiMocks.getFollowupQuestions.mockResolvedValue({
      code: 200,
      data: { questions: ["简历中的缓存方案请展开讲讲", "为什么考虑换工作"] },
    });

    const wrapper = mountModal();
    await flushPromises();

    clickButton("interview-review-questions");
    await flushPromises();

    const items = document.querySelectorAll('[data-testid="interview-review-question-item"]');
    expect(items.length).toBe(2);

    (items[0] as HTMLElement).click();
    await flushPromises();
    const textarea = document.querySelector<HTMLTextAreaElement>(
      'textarea[data-testid="interview-review-feedback-input"]',
    );
    expect(textarea?.value).toBe("简历中的缓存方案请展开讲讲");
    wrapper.unmount();
  });

  it("追问生成失败提示降级手动填写", async () => {
    apiMocks.getFollowupQuestions.mockRejectedValue(new Error("llm down"));

    const wrapper = mountModal();
    await flushPromises();

    clickButton("interview-review-questions");
    await flushPromises();

    expect(document.querySelector('[data-testid="interview-review-questions-list"]')).toBeNull();
    const textarea = document.querySelector<HTMLTextAreaElement>(
      'textarea[data-testid="interview-review-feedback-input"]',
    );
    expect(textarea).not.toBeNull();
    wrapper.unmount();
  });
});
