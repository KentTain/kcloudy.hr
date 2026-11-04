/**
 * CandidatesPage 页面测试：漏斗统计卡加载与点击联动阶段筛选、卡片流渲染、
 * 阶段操作出项与权限显隐（录入按钮/Offer 按钮）
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CandidatesPage from "@/hr/pages/candidates/CandidatesPage.vue";
import type { Application } from "@/hr/types/recruiting";

const permState = vi.hoisted(() => ({
  granted: new Set<string>([
    "hr:candidate:read",
    "hr:candidate:write",
    "hr:candidate:merge",
    "hr:interview:write",
    "hr:offer:write",
    "hr:requisition:read",
  ]),
}));

const apiMocks = vi.hoisted(() => ({
  getGlobalFunnel: vi.fn(),
  listRequisitions: vi.fn(),
  updateApplicationStage: vi.fn(),
  listCandidateCards: vi.fn(),
  createCandidate: vi.fn(),
  getCandidate: vi.fn(),
  updateCandidate: vi.fn(),
  deleteCandidate: vi.fn(),
  parseResume: vi.fn(),
  mergeCandidates: vi.fn(),
  getMergeSuggestions: vi.fn(),
  setBlacklist: vi.fn(),
  getApplication: vi.fn(),
  createInterview: vi.fn(),
  updateInterview: vi.fn(),
  createOffer: vi.fn(),
  sendOffer: vi.fn(),
  getApplicationOffer: vi.fn(),
  acceptOffer: vi.fn(),
  rejectOffer: vi.fn(),
  onboardOffer: vi.fn(),
  getPositionOptions: vi.fn(),
}));

vi.mock("@/hr/api/recruiting", () => ({
  getGlobalFunnel: apiMocks.getGlobalFunnel,
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
  getMergeSuggestions: apiMocks.getMergeSuggestions,
  setBlacklist: apiMocks.setBlacklist,
  getApplication: apiMocks.getApplication,
}));

vi.mock("@/hr/api/interview", () => ({
  createInterview: apiMocks.createInterview,
  updateInterview: apiMocks.updateInterview,
}));

vi.mock("@/hr/api/offer", () => ({
  createOffer: apiMocks.createOffer,
  sendOffer: apiMocks.sendOffer,
  getApplicationOffer: apiMocks.getApplicationOffer,
  acceptOffer: apiMocks.acceptOffer,
  rejectOffer: apiMocks.rejectOffer,
  onboardOffer: apiMocks.onboardOffer,
}));

vi.mock("@/hr/api/reference", () => ({
  getPositionOptions: apiMocks.getPositionOptions,
}));

vi.mock("@/framework/stores", () => ({
  useUserStore: () => ({
    hasPermission: (code: string) => permState.granted.has(code),
  }),
}));

vi.mock("@/framework/utils/feedback", () => ({
  confirmAction: vi.fn(async () => true),
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

function makeApplication(overrides: Partial<Application> = {}): Application {
  return {
    id: "app-1",
    candidate_id: "cand-1",
    candidate_name: "张三",
    requisition_id: "req-1",
    requisition_title: "后端工程师",
    stage: "pending_screening",
    stage_history: [],
    match_score: 82,
    apply_time: "2026-10-10T10:00:00",
    employee_id: null,
    ...overrides,
  };
}

function mountPage() {
  return mount(CandidatesPage, { attachTo: document.body });
}

function findButton(text: string): HTMLButtonElement | undefined {
  return document
    .querySelectorAll("button")
    .values()
    .find((el) => el.textContent?.trim() === text) as HTMLButtonElement | undefined;
}

beforeEach(() => {
  vi.resetAllMocks();
  permState.granted = new Set([
    "hr:candidate:read",
    "hr:candidate:write",
    "hr:candidate:merge",
    "hr:interview:write",
    "hr:offer:write",
    "hr:requisition:read",
  ]);
  apiMocks.getGlobalFunnel.mockResolvedValue({
    code: 200,
    data: {
      requisition_id: null,
      stats: [
        { stage: "pending_screening", count: 5 },
        { stage: "interviewing", count: 2 },
        { stage: "pre_hire", count: 1 },
      ],
    },
  });
  apiMocks.listRequisitions.mockResolvedValue({ code: 200, data: [], total: 0 });
  apiMocks.listCandidateCards.mockResolvedValue({
    code: 200,
    data: [
      makeApplication(),
      makeApplication({ id: "app-2", candidate_id: "cand-2", candidate_name: "李四", stage: "screening_passed" }),
    ],
    total: 2,
    page: 1,
    page_size: 12,
  });
  apiMocks.updateApplicationStage.mockResolvedValue({ code: 200, data: { id: "app-1" } });
  apiMocks.getMergeSuggestions.mockResolvedValue({ code: 200, data: [] });
  apiMocks.getApplicationOffer.mockResolvedValue({
    code: 200,
    data: { id: "offer-1", application_id: "app-1", salary_snapshot: {}, status: "sent", valid_until: null, sent_at: null },
  });
  apiMocks.acceptOffer.mockResolvedValue({ code: 200, data: { id: "offer-1", status: "accepted" } });
  apiMocks.rejectOffer.mockResolvedValue({ code: 200, data: { id: "offer-1", status: "rejected" } });
  apiMocks.onboardOffer.mockResolvedValue({
    code: 200,
    data: { employee_id: "emp-1", employee_no: "EMP0001" },
  });
  apiMocks.getPositionOptions.mockResolvedValue({ code: 200, data: [] });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("CandidatesPage", () => {
  it("挂载后拉取漏斗与卡片流，渲染候选人与阶段标签", async () => {
    mountPage();
    await flushPromises();

    expect(apiMocks.getGlobalFunnel).toHaveBeenCalled();
    expect(apiMocks.listCandidateCards).toHaveBeenCalled();
    const body = document.body.textContent ?? "";
    expect(body).toContain("张三");
    expect(body).toContain("李四");
    expect(body).toContain("待初筛");
  });

  it("漏斗点击阶段联动筛选，重查卡片流携带 stage 参数", async () => {
    mountPage();
    await flushPromises();
    expect(apiMocks.listCandidateCards).toHaveBeenCalledTimes(1);

    const stageCell = document.querySelector<HTMLButtonElement>('[data-testid="funnel-stage-pending_screening"]');
    expect(stageCell, "漏斗应渲染待初筛阶段").toBeTruthy();
    stageCell!.click();
    await flushPromises();

    const lastCall = apiMocks.listCandidateCards.mock.calls.at(-1)?.[0] as Record<string, unknown>;
    expect(lastCall.stage).toBe("pending_screening");
  });

  it("卡片操作随阶段出项：初筛通过点击流转并刷新", async () => {
    mountPage();
    await flushPromises();

    const passButton = findButton("初筛通过");
    expect(passButton, "待初筛卡片应有初筛通过按钮").toBeTruthy();
    passButton!.click();
    await flushPromises();

    expect(apiMocks.updateApplicationStage).toHaveBeenCalledWith("app-1", "screening_passed");
  });

  it("screening_passed 卡片出项「安排面试」，pre_hire 卡片出项「发起 Offer」", async () => {
    apiMocks.listCandidateCards.mockResolvedValue({
      code: 200,
      data: [
        makeApplication({ id: "app-2", candidate_id: "cand-2", stage: "screening_passed" }),
        makeApplication({ id: "app-3", candidate_id: "cand-3", candidate_name: "王五", stage: "pre_hire" }),
      ],
      total: 2,
    });
    mountPage();
    await flushPromises();

    expect(document.querySelector('[data-testid="card-arrange-interview"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="card-create-offer"]')).toBeTruthy();
  });

  it("offered 卡片点击「接受 Offer」：按申请查 offer 后调 acceptOffer 并刷新", async () => {
    apiMocks.listCandidateCards.mockResolvedValue({
      code: 200,
      data: [makeApplication({ stage: "offered" })],
      total: 1,
    });
    mountPage();
    await flushPromises();

    (document.querySelector('[data-testid="card-offer-accept"]') as HTMLButtonElement).click();
    await flushPromises();

    expect(apiMocks.getApplicationOffer).toHaveBeenCalledWith("app-1");
    expect(apiMocks.acceptOffer).toHaveBeenCalledWith("offer-1");
    expect(apiMocks.rejectOffer).not.toHaveBeenCalled();
  });

  it("offered 卡片点击「拒绝 Offer」调 rejectOffer；无 Offer 单时提示且不调状态机", async () => {
    apiMocks.listCandidateCards.mockResolvedValue({
      code: 200,
      data: [makeApplication({ stage: "offered" })],
      total: 1,
    });
    mountPage();
    await flushPromises();

    (document.querySelector('[data-testid="card-offer-reject"]') as HTMLButtonElement).click();
    await flushPromises();
    expect(apiMocks.rejectOffer).toHaveBeenCalledWith("offer-1");

    apiMocks.getApplicationOffer.mockResolvedValue({ code: 200, data: null });
    apiMocks.rejectOffer.mockClear();
    (document.querySelector('[data-testid="card-offer-reject"]') as HTMLButtonElement | null)?.click();
    await flushPromises();
    expect(apiMocks.rejectOffer).not.toHaveBeenCalled();
  });

  it("pre_onboard 卡片点击「办理入职」打开弹窗，确认后查 offer 调 onboardOffer", async () => {
    apiMocks.listCandidateCards.mockResolvedValue({
      code: 200,
      data: [makeApplication({ stage: "pre_onboard" })],
      total: 1,
    });
    mountPage();
    await flushPromises();

    (document.querySelector('[data-testid="card-onboard"]') as HTMLButtonElement).click();
    await flushPromises();

    const dialog = document.querySelector('[data-testid="offer-onboard-dialog"]');
    expect(dialog).toBeTruthy();
    const dateInput = dialog?.querySelector<HTMLInputElement>('input[type="date"]');
    expect(dateInput?.value).toMatch(/^\d{4}-\d{2}-\d{2}$/);

    (dialog?.querySelector('[data-testid="onboard-submit"]') as HTMLButtonElement).click();
    await flushPromises();

    expect(apiMocks.getApplicationOffer).toHaveBeenCalledWith("app-1");
    expect(apiMocks.onboardOffer).toHaveBeenCalledWith(
      "offer-1",
      expect.objectContaining({ hire_date: expect.any(String) }),
    );
  });

  it("录入按钮与 Offer 按钮随权限显隐，无漏斗权限时降级隐藏且不请求", async () => {
    const withPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-candidate-form"]')).toBeTruthy();
    withPerm.unmount();
    document.body.innerHTML = "";

    permState.granted = new Set(["hr:candidate:read"]);
    apiMocks.getGlobalFunnel.mockClear();
    const withoutPerm = mountPage();
    await flushPromises();

    expect(document.querySelector('[data-testid="open-candidate-form"]')).toBeNull();
    expect(document.querySelector('[data-testid="card-create-offer"]')).toBeNull();
    expect(apiMocks.getGlobalFunnel).not.toHaveBeenCalled();
    withoutPerm.unmount();
  });
});
