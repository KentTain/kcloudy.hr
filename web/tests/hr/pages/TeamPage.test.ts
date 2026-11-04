/**
 * TeamPage（console 团队工作台）页面测试：团队招聘 enabled 门控与部门名映射、
 * 我的面试懒加载与待评价入口、待我评分列表与评分弹窗提交
 */
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TeamPage from "@/hr/pages/team/TeamPage.vue";
import type { Requisition } from "@/hr/types/recruiting";
import type { TeamInterviewItem, TeamReviewItem } from "@/hr/types/selfService";

const apiMocks = vi.hoisted(() => ({
  listTeamRequisitions: vi.fn(),
  listTeamInterviews: vi.fn(),
  listTeamReviews: vi.fn(),
  submitTeamReviewScore: vi.fn(),
  getOrgTree: vi.fn(),
}));

const orgState = vi.hoisted(() => ({
  organizations: [] as { id: string; name: string; code?: string | null; is_leader?: boolean }[],
}));

vi.mock("@/framework/stores", () => ({
  useUserStore: () => ({
    userInfo: { organizations: orgState.organizations },
  }),
}));

vi.mock("@/hr/api/team", () => ({
  listTeamRequisitions: apiMocks.listTeamRequisitions,
  listTeamInterviews: apiMocks.listTeamInterviews,
  listTeamReviews: apiMocks.listTeamReviews,
  submitTeamReviewScore: apiMocks.submitTeamReviewScore,
}));

vi.mock("@/hr/api/reference", () => ({
  getOrgTree: apiMocks.getOrgTree,
  getPositionOptions: vi.fn(),
  listEmployeeSalaryPackages: vi.fn(),
  getBandComparison: vi.fn(),
  listSalaryItemOptions: vi.fn(),
}));

vi.mock("@/framework/utils/feedback", () => ({
  confirmAction: vi.fn(async () => true),
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

const REQUISITION: Requisition = {
  id: "req-1",
  req_no: "REQ-001",
  title: "后端工程师",
  org_id: "org-11",
  position_id: "pos-1",
  headcount: 2,
  job_level: "P5",
  salary_min: 15000,
  salary_max: 25000,
  priority: "high",
  status: "open",
  jd: null,
  filled_count: 1,
  postings: [],
};

const INTERVIEWS: TeamInterviewItem[] = [
  {
    id: "itv-1",
    round: 1,
    scheduled_at: "2026-10-20 10:00",
    interview_form: "onsite",
    result: "pending",
    candidate_name: "李四",
    requisition_id: "req-1",
    requisition_title: "后端工程师",
  },
  {
    id: "itv-2",
    round: 2,
    scheduled_at: "2026-10-18 14:00",
    interview_form: "phone",
    result: "pass",
    candidate_name: "王五",
    requisition_id: "req-1",
    requisition_title: "后端工程师",
  },
];

const REVIEWS: TeamReviewItem[] = [
  {
    id: "rev-1",
    cycle_id: "cyc-1",
    cycle_name: "2026-H1",
    employee_no: "EMP001",
    employee_name: "张三",
    goal_count: 2,
    weighted_progress: 80,
    self_score: 85,
  },
];

const ORG_TREE = [
  {
    id: "org-1",
    name: "总部",
    parent_id: null,
    children: [{ id: "org-11", name: "研发部", parent_id: "org-1", children: [] }],
  },
];

function mountPage(): VueWrapper {
  return mount(TeamPage, { attachTo: document.body });
}

function switchTab(testid: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  if (!el) throw new Error(`element not found: ${testid}`);
  el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
}

function clickButton(testid: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  if (el instanceof HTMLElement) el.click();
}

function setInputValue(testid: string, value: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  const input = el?.querySelector("input") as HTMLInputElement | null;
  if (!input) throw new Error(`input not found: ${testid}`);
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

beforeEach(() => {
  vi.resetAllMocks();
  orgState.organizations = [{ id: "org-1", name: "总部", is_leader: true }];
  apiMocks.listTeamRequisitions.mockResolvedValue({
    code: 200,
    data: [REQUISITION],
    total: 1,
    page: 1,
    page_size: 10,
  });
  apiMocks.listTeamInterviews.mockResolvedValue({ code: 200, data: INTERVIEWS });
  apiMocks.listTeamReviews.mockResolvedValue({ code: 200, data: REVIEWS });
  apiMocks.submitTeamReviewScore.mockResolvedValue({ code: 200, data: { id: "rev-1" } });
  apiMocks.getOrgTree.mockResolvedValue({ code: 200, data: ORG_TREE });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("TeamPage", () => {
  it("团队招聘默认页签懒加载（enabled 门控），部门名经组织树映射", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(apiMocks.listTeamRequisitions).toHaveBeenCalledWith({ page: 1, page_size: 10 });
    expect(apiMocks.getOrgTree).toHaveBeenCalledTimes(1);
    const table =
      document.querySelector('[data-testid="team-requisition-table"]')?.textContent ?? "";
    expect(table).toContain("REQ-001");
    expect(table).toContain("研发部");
    expect(apiMocks.listTeamInterviews).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("我的面试页签懒加载，展示形式/结果标签与待评价入口", async () => {
    const wrapper = mountPage();
    await flushPromises();
    expect(apiMocks.listTeamInterviews).not.toHaveBeenCalled();

    switchTab("team-tab-interviews");
    await flushPromises();

    expect(apiMocks.listTeamInterviews).toHaveBeenCalledTimes(1);
    const pending =
      document.querySelector('[data-testid="team-interview-itv-1"]')?.textContent ?? "";
    expect(pending).toContain("李四");
    expect(pending).toContain("现场面试");
    expect(document.querySelector('[data-testid="team-interview-evaluate-itv-1"]')).not.toBeNull();

    const passed =
      document.querySelector('[data-testid="team-interview-itv-2"]')?.textContent ?? "";
    expect(passed).toContain("通过");
    expect(document.querySelector('[data-testid="team-interview-evaluate-itv-2"]')).toBeNull();
    wrapper.unmount();
  });

  it("待我评分页签懒加载，评分弹窗提交后刷新列表", async () => {
    const wrapper = mountPage();
    await flushPromises();

    switchTab("team-tab-reviews");
    await flushPromises();

    expect(apiMocks.listTeamReviews).toHaveBeenCalledTimes(1);
    const row = document.querySelector('[data-testid="team-review-rev-1"]')?.textContent ?? "";
    expect(row).toContain("张三");
    expect(row).toContain("80%");

    clickButton("team-review-score-rev-1");
    await flushPromises();
    expect(document.querySelector('[data-testid="team-score-modal"]')?.textContent).toContain(
      "提交评分"
    );

    setInputValue("team-score-input", "88");
    const select = wrapper.findComponent({ name: "Select" });
    select.vm.$emit("update:modelValue", "A");
    await flushPromises();

    clickButton("team-score-submit");
    await flushPromises();

    expect(apiMocks.submitTeamReviewScore).toHaveBeenCalledWith("rev-1", {
      score: 88,
      rating: "A",
      self_score: null,
    });
    expect(apiMocks.listTeamReviews).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("评分缺少评分值或评级时不提交", async () => {
    const wrapper = mountPage();
    await flushPromises();

    switchTab("team-tab-reviews");
    await flushPromises();

    clickButton("team-review-score-rev-1");
    await flushPromises();

    clickButton("team-score-submit");
    await flushPromises();

    expect(apiMocks.submitTeamReviewScore).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("非组织负责人展示整页空态，不拉取任何列表", async () => {
    orgState.organizations = [{ id: "org-1", name: "总部", is_leader: false }];
    const wrapper = mountPage();
    await flushPromises();

    expect(document.querySelector('[data-testid="team-not-leader"]')).not.toBeNull();
    expect(document.querySelector('[data-testid="team-tab-requisitions"]')).toBeNull();
    expect(apiMocks.listTeamRequisitions).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("成员归属多组织时任一负责人身份即可访问", async () => {
    orgState.organizations = [
      { id: "org-1", name: "总部", is_leader: false },
      { id: "org-2", name: "研发部", is_leader: true },
    ];
    const wrapper = mountPage();
    await flushPromises();

    expect(document.querySelector('[data-testid="team-not-leader"]')).toBeNull();
    expect(apiMocks.listTeamRequisitions).toHaveBeenCalled();
    wrapper.unmount();
  });
});
