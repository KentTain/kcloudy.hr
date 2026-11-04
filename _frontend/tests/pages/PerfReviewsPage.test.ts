/**
 * PerfReviewsPage 页面测试：评估列表渲染、评分/校准按钮随周期状态与评估状态显隐、
 * 发起评估按钮权限门控、选中周期加载评级分布
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PerfReviewsPage from "@/hr/pages/perf-reviews/PerfReviewsPage.vue";
import type { PerfReviewItem } from "@/hr/types/perf";

const permState = vi.hoisted(() => ({
  granted: new Set<string>(["hr:perf_review:read"]),
}));

const apiMocks = vi.hoisted(() => ({
  listPerfCycles: vi.fn(),
  getPerfCycle: vi.fn(),
  createPerfCycle: vi.fn(),
  updatePerfCycle: vi.fn(),
  deletePerfCycle: vi.fn(),
  transitionPerfCycle: vi.fn(),
  getPerfDistribution: vi.fn(),
  listPerfGoals: vi.fn(),
  submitPerfGoals: vi.fn(),
  updatePerfGoal: vi.fn(),
  updatePerfGoalProgress: vi.fn(),
  deletePerfGoal: vi.fn(),
  listPerfReviews: vi.fn(),
  createPerfReviews: vi.fn(),
  scorePerfReview: vi.fn(),
  calibratePerfReview: vi.fn(),
  listEmployees: vi.fn(),
}));

vi.mock("@/hr/api/perf", () => ({
  listPerfCycles: apiMocks.listPerfCycles,
  getPerfCycle: apiMocks.getPerfCycle,
  createPerfCycle: apiMocks.createPerfCycle,
  updatePerfCycle: apiMocks.updatePerfCycle,
  deletePerfCycle: apiMocks.deletePerfCycle,
  transitionPerfCycle: apiMocks.transitionPerfCycle,
  getPerfDistribution: apiMocks.getPerfDistribution,
  listPerfGoals: apiMocks.listPerfGoals,
  submitPerfGoals: apiMocks.submitPerfGoals,
  updatePerfGoal: apiMocks.updatePerfGoal,
  updatePerfGoalProgress: apiMocks.updatePerfGoalProgress,
  deletePerfGoal: apiMocks.deletePerfGoal,
  listPerfReviews: apiMocks.listPerfReviews,
  createPerfReviews: apiMocks.createPerfReviews,
  scorePerfReview: apiMocks.scorePerfReview,
  calibratePerfReview: apiMocks.calibratePerfReview,
}));

vi.mock("@/hr/api/employee", () => ({
  listEmployees: apiMocks.listEmployees,
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

function buildReview(overrides: Partial<PerfReviewItem>): PerfReviewItem {
  return {
    id: "rev-1",
    cycle_id: "cyc-1",
    cycle_status: "scoring",
    employee_id: "emp-1",
    employee_no: "E001",
    employee_name: "张三",
    reviewer_employee_id: "emp-9",
    reviewer_name: "李经理",
    goal_count: 3,
    weighted_progress: 80,
    self_score: null,
    score: null,
    rating: null,
    calibrated_rating: null,
    calibration_comment: null,
    calibrated_at: null,
    coefficient: null,
    status: "pending",
    created_at: null,
    ...overrides,
  };
}

const REVIEWS: PerfReviewItem[] = [
  buildReview({ id: "rev-1", status: "pending", cycle_status: "scoring" }),
  buildReview({
    id: "rev-2",
    employee_id: "emp-2",
    employee_name: "王五",
    status: "submitted",
    score: 86,
    rating: "B",
    cycle_status: "calibrating",
  }),
  buildReview({
    id: "rev-3",
    employee_id: "emp-3",
    employee_name: "赵六",
    status: "calibrated",
    score: 92,
    rating: "A",
    calibrated_rating: "S",
    calibrated_at: "2026-10-18T00:00:00Z",
    coefficient: 1.5,
    cycle_status: "closed",
  }),
];

function mountPage() {
  return mount(PerfReviewsPage, { attachTo: document.body });
}

beforeEach(() => {
  vi.resetAllMocks();
  permState.granted = new Set([
    "hr:perf_review:read",
    "hr:perf_review:write",
    "hr:perf:calibrate",
  ]);
  apiMocks.listPerfCycles.mockResolvedValue({
    code: 200,
    data: [
      {
        id: "cyc-1",
        name: "2026-H1",
        start_date: "2026-01-01",
        end_date: "2026-06-30",
        status: "scoring",
        goal_count: 3,
        review_count: 3,
        created_at: null,
        updated_at: null,
      },
    ],
    total: 1,
    page: 1,
    page_size: 100,
  });
  apiMocks.listPerfReviews.mockResolvedValue({
    code: 200,
    data: REVIEWS,
    total: 3,
    page: 1,
    page_size: 20,
  });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("PerfReviewsPage", () => {
  it("挂载后拉取评估列表并渲染行数据", async () => {
    mountPage();
    await flushPromises();

    expect(apiMocks.listPerfReviews).toHaveBeenCalled();
    const body = document.body.textContent ?? "";
    expect(body).toContain("张三");
    expect(body).toContain("李经理");
    expect(body).toContain("赵六");
  });

  it("发起评估按钮随 hr:perf_review:write 权限显隐", async () => {
    const withPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="review-launch"]')).toBeTruthy();
    withPerm.unmount();
    document.body.innerHTML = "";

    permState.granted = new Set(["hr:perf_review:read"]);
    const withoutPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="review-launch"]')).toBeNull();
    withoutPerm.unmount();
  });

  it("评分/校准按钮按周期状态与评估状态渲染", async () => {
    mountPage();
    await flushPromises();

    // scoring + 未校准 → 可评分；calibrating + 已提交 → 仅可校准；closed 已校准 → 均无
    expect(document.querySelector('[data-testid="review-score-rev-1"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="review-calibrate-rev-1"]')).toBeNull();
    expect(document.querySelector('[data-testid="review-score-rev-2"]')).toBeNull();
    expect(document.querySelector('[data-testid="review-calibrate-rev-2"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="review-score-rev-3"]')).toBeNull();
    expect(document.querySelector('[data-testid="review-calibrate-rev-3"]')).toBeNull();
  });

  it("评分按钮仅随 hr:perf_review:write 显隐，校准仅随 hr:perf:calibrate 显隐", async () => {
    permState.granted = new Set(["hr:perf_review:read", "hr:perf:calibrate"]);
    mountPage();
    await flushPromises();

    expect(document.querySelector('[data-testid="review-score-rev-1"]')).toBeNull();
    expect(document.querySelector('[data-testid="review-calibrate-rev-2"]')).toBeTruthy();
  });

  it("选中周期后加载评级分布", async () => {
    apiMocks.getPerfDistribution.mockResolvedValue({
      code: 200,
      data: {
        cycle_id: "cyc-1",
        total: 3,
        ratings: {
          S: { count: 1, percent: 33.33 },
          A: { count: 1, percent: 33.33 },
          B: { count: 1, percent: 33.33 },
          C: { count: 0, percent: 0 },
          D: { count: 0, percent: 0 },
        },
        rules: { S: 10, A: 20 },
      },
    });
    const wrapper = mountPage();
    await flushPromises();

    expect(document.querySelector('[data-testid="review-distribution"]')).toBeNull();

    // reka Select 弹层在 jsdom 不展开，经组件实例驱动 v-model（页面第 1 个 Select = 周期筛选）
    const select = wrapper.findComponent({ name: "Select" });
    expect(select.exists()).toBe(true);
    select.vm.$emit("update:modelValue", "cyc-1");
    await flushPromises();

    expect(apiMocks.getPerfDistribution).toHaveBeenCalledWith("cyc-1");
    const body = document.body.textContent ?? "";
    expect(body).toContain("评级分布");
    expect(body).toContain("S≤10%");
  });
});
