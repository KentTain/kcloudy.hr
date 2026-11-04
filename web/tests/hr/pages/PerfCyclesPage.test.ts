/**
 * PerfCyclesPage 页面测试：周期列表渲染、状态机操作按钮随状态与权限显隐、
 * 推进二次确认与调用、新建按钮权限门控
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PerfCyclesPage from "@/hr/pages/perf-cycles/PerfCyclesPage.vue";
import type { PerfCycleItem } from "@/hr/types/perf";

const permState = vi.hoisted(() => ({
  granted: new Set<string>(["hr:perf_cycle:read"]),
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

const CYCLES: PerfCycleItem[] = [
  {
    id: "cyc-1",
    name: "2026-H1",
    start_date: "2026-01-01",
    end_date: "2026-06-30",
    status: "draft",
    goal_count: 0,
    review_count: 0,
    created_at: null,
    updated_at: null,
  },
  {
    id: "cyc-2",
    name: "2025-H2",
    start_date: "2025-07-01",
    end_date: "2025-12-31",
    status: "closed",
    goal_count: 6,
    review_count: 5,
    created_at: null,
    updated_at: null,
  },
];

function mountPage() {
  return mount(PerfCyclesPage, { attachTo: document.body });
}

beforeEach(() => {
  vi.resetAllMocks();
  permState.granted = new Set([
    "hr:perf_cycle:read",
    "hr:perf_cycle:write",
    "hr:perf_cycle:delete",
  ]);
  apiMocks.listPerfCycles.mockResolvedValue({
    code: 200,
    data: CYCLES,
    total: 2,
    page: 1,
    page_size: 20,
  });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("PerfCyclesPage", () => {
  it("挂载后拉取周期列表并渲染行数据", async () => {
    mountPage();
    await flushPromises();

    expect(apiMocks.listPerfCycles).toHaveBeenCalled();
    const body = document.body.textContent ?? "";
    expect(body).toContain("2026-H1");
    expect(body).toContain("2025-H2");
  });

  it("新建周期按钮随 hr:perf_cycle:write 权限显隐", async () => {
    const withPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="cycle-create"]')).toBeTruthy();
    withPerm.unmount();
    document.body.innerHTML = "";

    permState.granted = new Set(["hr:perf_cycle:read"]);
    const withoutPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="cycle-create"]')).toBeNull();
    withoutPerm.unmount();
  });

  it("状态机操作按钮按状态渲染：draft 行出激活，closed 行无推进按钮", async () => {
    mountPage();
    await flushPromises();

    expect(
      document.querySelector('[data-testid="cycle-transition-activate-cyc-1"]'),
    ).toBeTruthy();
    expect(
      document.querySelector('[data-testid="cycle-transition-activate-cyc-2"]'),
    ).toBeNull();
    expect(document.querySelector('[data-testid="cycle-edit-cyc-1"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="cycle-edit-cyc-2"]')).toBeNull();
    expect(document.querySelector('[data-testid="cycle-delete-cyc-1"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="cycle-delete-cyc-2"]')).toBeNull();
  });

  it("激活经二次确认后调用状态机接口并刷新列表", async () => {
    apiMocks.transitionPerfCycle.mockResolvedValue({ code: 200, data: null });
    mountPage();
    await flushPromises();

    const button = document.querySelector(
      '[data-testid="cycle-transition-activate-cyc-1"]',
    ) as HTMLButtonElement;
    button.click();
    await flushPromises();

    expect(apiMocks.transitionPerfCycle).toHaveBeenCalledWith("cyc-1", "activate");
    expect(apiMocks.listPerfCycles).toHaveBeenCalledTimes(2);
  });
});
