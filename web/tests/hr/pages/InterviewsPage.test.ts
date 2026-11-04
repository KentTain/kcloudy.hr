/**
 * InterviewsPage 页面测试：周视图按日分组渲染、列表视图切换、
 * 「我参与的」内存筛选、日程卡评价弹窗提交、安排按钮权限显隐
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import InterviewsPage from "@/hr/pages/interviews/InterviewsPage.vue";
import type { WeeklyInterviews } from "@/hr/types/recruiting";

const permState = vi.hoisted(() => ({ granted: new Set<string>(["hr:interview:read"]) }));

const apiMocks = vi.hoisted(() => ({
  getWeeklyInterviews: vi.fn(),
  updateInterview: vi.fn(),
  createInterview: vi.fn(),
  submitInterviewSummary: vi.fn(),
  getInterviewDetail: vi.fn(),
  getFollowupQuestions: vi.fn(),
  listRequisitions: vi.fn(),
  updateApplicationStage: vi.fn(),
  listCandidateCards: vi.fn(),
  createCandidate: vi.fn(),
  getCandidate: vi.fn(),
  updateCandidate: vi.fn(),
  deleteCandidate: vi.fn(),
  parseResume: vi.fn(),
  mergeCandidates: vi.fn(),
  setBlacklist: vi.fn(),
  getApplication: vi.fn(),
  createOffer: vi.fn(),
  sendOffer: vi.fn(),
}));

vi.mock("@/hr/api/interview", () => ({
  getWeeklyInterviews: apiMocks.getWeeklyInterviews,
  updateInterview: apiMocks.updateInterview,
  createInterview: apiMocks.createInterview,
  submitInterviewSummary: apiMocks.submitInterviewSummary,
  getInterviewDetail: apiMocks.getInterviewDetail,
  getFollowupQuestions: apiMocks.getFollowupQuestions,
}));

vi.mock("@/hr/api/recruiting", () => ({
  listRequisitions: apiMocks.listRequisitions,
  updateApplicationStage: apiMocks.updateApplicationStage,
}));

vi.mock("@/hr/api/candidate", () => ({
  listCandidateCards: apiMocks.listCandidateCards,
  createCandidate: apiMocks.createCandidate,
  getCandidate: apiMocks.getCandidate,
  updateCandidate: apiMocks.updateCandidate,
  deleteCandidate: apiMocks.deleteCandidate,
  parseResume: apiMocks.parseResume,
  mergeCandidates: apiMocks.mergeCandidates,
  setBlacklist: apiMocks.setBlacklist,
  getApplication: apiMocks.getApplication,
}));

vi.mock("@/hr/api/offer", () => ({
  createOffer: apiMocks.createOffer,
  sendOffer: apiMocks.sendOffer,
}));

vi.mock("@/framework/stores", () => ({
  useUserStore: () => ({
    hasPermission: (code: string) => permState.granted.has(code),
    userInfo: { id: "user-me" },
  }),
}));

vi.mock("@/framework/utils/feedback", () => ({
  confirmAction: vi.fn(async () => true),
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

function dayItem(overrides: Record<string, unknown> = {}) {
  return {
    id: "iv-1",
    application_id: "app-1",
    candidate_name: "张三",
    requisition_title: "后端工程师",
    round: 1,
    interviewer_id: "user-me",
    scheduled_at: "2026-10-12T10:00:00",
    interview_form: "onsite",
    result: "pending",
    ...overrides,
  };
}

const WEEKLY: WeeklyInterviews = {
  start: "2026-10-12",
  days: {
    "2026-10-12": [
      dayItem(),
      dayItem({
        id: "iv-2",
        candidate_name: "李四",
        interviewer_id: "user-other",
        scheduled_at: "2026-10-12T14:00:00",
        interview_form: "online",
        result: "pass",
      }),
    ],
    "2026-10-13": [dayItem({ id: "iv-3", candidate_name: "王五", scheduled_at: "2026-10-13T09:30:00" })],
    "2026-10-14": [],
    "2026-10-15": [],
    "2026-10-16": [],
    "2026-10-17": [],
    "2026-10-18": [],
  },
};

function mountPage() {
  return mount(InterviewsPage, { attachTo: document.body });
}

beforeEach(() => {
  vi.resetAllMocks();
  permState.granted = new Set(["hr:interview:read", "hr:interview:write"]);
  apiMocks.getWeeklyInterviews.mockResolvedValue({ code: 200, data: WEEKLY });
  apiMocks.updateInterview.mockResolvedValue({ code: 200, data: { id: "iv-1", result: "pass" } });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("InterviewsPage", () => {
  it("挂载后拉取周视图并按日分组渲染日程卡", async () => {
    mountPage();
    await flushPromises();

    expect(apiMocks.getWeeklyInterviews).toHaveBeenCalled();
    expect(document.querySelector('[data-testid="interview-day-2026-10-12"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="interview-card-iv-1"]')).toBeTruthy();
    const body = document.body.textContent ?? "";
    expect(body).toContain("张三");
    expect(body).toContain("李四");
    expect(body).toContain("王五");
  });

  it("切换列表视图渲染扁平化表格行", async () => {
    mountPage();
    await flushPromises();

    const toggle = document.querySelector<HTMLButtonElement>('[data-testid="interview-view-list"]');
    toggle!.click();
    await flushPromises();

    expect(document.querySelector('[data-testid="interview-list-table"]')).toBeTruthy();
    const body = document.body.textContent ?? "";
    expect(body).toContain("张三");
    expect(body).toContain("第 1 轮");
  });

  it("「我参与的」过滤面试官非当前用户的安排", async () => {
    mountPage();
    await flushPromises();

    const checkbox = document.querySelector<HTMLElement>('[data-testid="interview-mine-only"]');
    expect(checkbox).toBeTruthy();
    const input = checkbox!.querySelector("input") ?? checkbox;
    input!.dispatchEvent(new Event("click", { bubbles: true }));
    (input as HTMLInputElement).checked = true;
    (input as HTMLInputElement).dispatchEvent(new Event("change", { bubbles: true }));
    await flushPromises();

    const body = document.body.textContent ?? "";
    expect(body).toContain("张三");
    expect(body).not.toContain("李四");
  });

  it("点击日程卡打开评价弹窗，提交结论调用 updateInterview", async () => {
    mountPage();
    await flushPromises();

    const card = document.querySelector<HTMLElement>('[data-testid="interview-card-iv-1"]');
    card!.click();
    await flushPromises();

    expect(document.querySelector('[data-testid="interview-review-dialog"]')).toBeTruthy();

    const feedbackHost = document.querySelector('[data-testid="interview-review-feedback-input"]');
    const textarea = (feedbackHost?.querySelector("textarea") ?? feedbackHost) as HTMLTextAreaElement | null;
    textarea!.value = "基础扎实，通过";
    textarea!.dispatchEvent(new Event("input"));
    await flushPromises();

    const submit = document.querySelector<HTMLElement>('[data-testid="interview-review-submit"]');
    submit!.click();
    await flushPromises();

    expect(apiMocks.updateInterview).toHaveBeenCalledWith("iv-1", {
      result: "pass",
      feedback: "基础扎实，通过",
    });
  });

  it("安排面试按钮随 hr:interview:write 权限显隐", async () => {
    const withPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-interview-quick"]')).toBeTruthy();
    withPerm.unmount();
    document.body.innerHTML = "";

    permState.granted = new Set(["hr:interview:read"]);
    const withoutPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-interview-quick"]')).toBeNull();
    withoutPerm.unmount();
  });
});
