/**
 * SelfServicePage（console 员工自助）页面测试：档案渲染与未关联空态、
 * 薪酬单懒加载与明细弹窗、团队成员 enabled 门控与部门名映射、
 * 我的目标（分组渲染 + active 周期进度更新）、我的绩效（系数仅收口）、
 * 变更申请弹窗（仅提交变更项）与我的申请撤销（二期批 E）
 */
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SelfServicePage from "@/hr/pages/self-service/SelfServicePage.vue";
import type { Employee } from "@/hr/types/employee";
import type { ChangeRequestSummary, MyProfileData, PaySlipDetail, PaySlipSummary } from "@/hr/types/selfService";

const apiMocks = vi.hoisted(() => ({
  getMyProfile: vi.fn(),
  listMyPaySlips: vi.fn(),
  getMyPaySlip: vi.fn(),
  listTeamEmployees: vi.fn(),
  getOrgTree: vi.fn(),
  getMyGoals: vi.fn(),
  getMyReviews: vi.fn(),
  updateMyGoalProgress: vi.fn(),
  listMyChangeRequests: vi.fn(),
  submitChangeRequest: vi.fn(),
  cancelChangeRequest: vi.fn(),
}));

vi.mock("@/hr/api/selfService", () => ({
  getMyProfile: apiMocks.getMyProfile,
  listMyPaySlips: apiMocks.listMyPaySlips,
  getMyPaySlip: apiMocks.getMyPaySlip,
  listTeamEmployees: apiMocks.listTeamEmployees,
  getMyGoals: apiMocks.getMyGoals,
  getMyReviews: apiMocks.getMyReviews,
  updateMyGoalProgress: apiMocks.updateMyGoalProgress,
  listMyChangeRequests: apiMocks.listMyChangeRequests,
  submitChangeRequest: apiMocks.submitChangeRequest,
  cancelChangeRequest: apiMocks.cancelChangeRequest,
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

const EMPLOYEE: Employee = {
  id: "emp-me",
  employee_no: "EMP001",
  name: "张三",
  gender: "男",
  phone: "13800000000",
  work_email: "zhang@ex.com",
  org_id: "org-11",
  position_id: "pos-1",
  job_level: "P5",
  status: "regular",
  hire_date: "2024-03-01",
  regular_date: "2024-09-01",
  offboard_date: null,
  user_id: "user-1",
  has_account: true,
};

const PROFILE: MyProfileData = {
  profile: { ...EMPLOYEE, birth_date: "1995-01-01", id_card_masked: "110***", bank_card_masked: "622***" },
  attributes: [
    {
      definition_id: "def-1",
      group_id: "grp-1",
      name: "紧急联系人",
      data_type: "text",
      ext_data: null,
      is_require: false,
      can_edit: true,
      sort: 1,
      value: "李四",
      raw_value: "李四",
    },
    {
      definition_id: "def-2",
      group_id: "grp-1",
      name: "家庭住址",
      data_type: "text",
      ext_data: { self_editable: true },
      is_require: false,
      can_edit: true,
      sort: 2,
      value: "朝阳区",
      raw_value: "朝阳区",
    },
  ],
};

const PAY_SLIPS: PaySlipSummary[] = [
  { period: "2026-09", pay_date: "2026-10-15", item_count: 2, total_amount: 15000 },
];

const PAY_SLIP_DETAIL: PaySlipDetail = {
  period: "2026-09",
  pay_date: "2026-10-15",
  total_amount: 15000,
  items: [
    { item_code: "base_salary", amount: 12000, note: null },
    { item_code: "bonus", amount: 3000, note: "季度奖" },
  ],
};

const TEAM: Employee[] = [
  EMPLOYEE,
  { ...EMPLOYEE, id: "emp-2", employee_no: "EMP002", name: "王五", org_id: "org-12", status: "probation" },
];

const ORG_TREE = [
  {
    id: "org-1",
    name: "总部",
    parent_id: null,
    children: [
      { id: "org-11", name: "研发部", parent_id: "org-1", children: [] },
      { id: "org-12", name: "市场部", parent_id: "org-1", children: [] },
    ],
  },
];

const MY_GOALS = [
  {
    cycle_id: "cyc-1",
    cycle_name: "2026-H1",
    cycle_status: "active",
    start_date: "2026-01-01",
    end_date: "2026-06-30",
    goals: [
      {
        id: "goal-1",
        code: "G-001",
        name: "交付达成",
        weight: 60,
        target_value: null,
        actual_value: "8/10",
        progress: 80,
        status: "open",
      },
    ],
  },
  {
    cycle_id: "cyc-0",
    cycle_name: "2025-H2",
    cycle_status: "closed",
    start_date: "2025-07-01",
    end_date: "2025-12-31",
    goals: [
      {
        id: "goal-0",
        code: "G-000",
        name: "质量提升",
        weight: 40,
        target_value: null,
        actual_value: null,
        progress: 100,
        status: "completed",
      },
    ],
  },
];

const MY_REVIEWS = [
  {
    id: "rev-1",
    cycle_id: "cyc-1",
    cycle_name: "2026-H1",
    cycle_status: "scoring",
    status: "pending",
    self_score: null,
    score: null,
    rating: null,
    final_rating: null,
    coefficient: null,
  },
  {
    id: "rev-0",
    cycle_id: "cyc-0",
    cycle_name: "2025-H2",
    cycle_status: "closed",
    status: "calibrated",
    self_score: 85,
    score: 88,
    rating: "A",
    final_rating: "A",
    coefficient: 1.2,
  },
];

const CHANGE_REQUESTS: ChangeRequestSummary[] = [
  {
    id: "ar-1",
    biz_type: "profile_change",
    title: "更新家庭住址",
    status: "pending",
    created_at: "2026-10-18T10:00:00Z",
    approver_id: null,
    approve_comment: null,
  },
];

function mountPage(): VueWrapper {
  return mount(SelfServicePage, { attachTo: document.body });
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
  apiMocks.getMyProfile.mockResolvedValue({ code: 200, data: PROFILE });
  apiMocks.listMyPaySlips.mockResolvedValue({ code: 200, data: PAY_SLIPS });
  apiMocks.getMyPaySlip.mockResolvedValue({ code: 200, data: PAY_SLIP_DETAIL });
  apiMocks.listTeamEmployees.mockResolvedValue({
    code: 200,
    data: TEAM,
    total: 2,
    page: 1,
    page_size: 10,
  });
  apiMocks.getOrgTree.mockResolvedValue({ code: 200, data: ORG_TREE });
  apiMocks.getMyGoals.mockResolvedValue({ code: 200, data: MY_GOALS });
  apiMocks.getMyReviews.mockResolvedValue({ code: 200, data: MY_REVIEWS });
  apiMocks.updateMyGoalProgress.mockResolvedValue({
    code: 200,
    data: { id: "goal-1", progress: 90, actual_value: "9/10" },
  });
  apiMocks.listMyChangeRequests.mockResolvedValue({ code: 200, data: CHANGE_REQUESTS });
  apiMocks.submitChangeRequest.mockResolvedValue({ code: 200, data: { id: "ar-1", status: "pending" } });
  apiMocks.cancelChangeRequest.mockResolvedValue({ code: 200, data: { id: "ar-1", status: "cancelled" } });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("SelfServicePage", () => {
  it("我的档案默认渲染：个人信息头 + 基础信息 + 扩展属性，仅调档案接口", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(document.querySelector('[data-testid="self-profile-name"]')?.textContent).toContain("张三");
    const base = document.querySelector('[data-testid="self-base-info"]')?.textContent ?? "";
    expect(base).toContain("2024-03-01");
    expect(base).toContain("P5");
    const attrs = document.querySelector('[data-testid="self-attributes"]')?.textContent ?? "";
    expect(attrs).toContain("紧急联系人");
    expect(attrs).toContain("李四");
    expect(apiMocks.getMyProfile).toHaveBeenCalledTimes(1);
    expect(apiMocks.listMyPaySlips).not.toHaveBeenCalled();
    expect(apiMocks.listTeamEmployees).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("未关联员工档案时展示空态", async () => {
    apiMocks.getMyProfile.mockRejectedValue(new Error("404"));
    const wrapper = mountPage();
    await flushPromises();

    expect(document.querySelector('[data-testid="self-profile-missing"]')?.textContent).toContain("尚未关联员工档案");
    expect(document.querySelector('[data-testid="self-tab-team"]')).toBeNull();
    wrapper.unmount();
  });

  it("薪酬单页签懒加载列表，查看明细弹窗展示分项与合计", async () => {
    const wrapper = mountPage();
    await flushPromises();
    expect(apiMocks.listMyPaySlips).not.toHaveBeenCalled();

    switchTab("self-tab-payslips");
    await flushPromises();

    expect(apiMocks.listMyPaySlips).toHaveBeenCalledTimes(1);
    const row = document.querySelector('[data-testid="self-payslip-2026-09"]')?.textContent ?? "";
    expect(row).toContain("2026-09");
    expect(row).toContain("¥15,000.00");

    clickButton("self-payslip-detail-2026-09");
    await flushPromises();

    expect(apiMocks.getMyPaySlip).toHaveBeenCalledWith("2026-09");
    const detail = document.querySelector('[data-testid="self-payslip-items"]')?.textContent ?? "";
    expect(detail).toContain("base_salary");
    expect(detail).toContain("季度奖");
    expect(detail).toContain("¥12,000.00");
    wrapper.unmount();
  });

  it("团队成员页签懒加载（enabled 门控），部门名经组织树映射", async () => {
    const wrapper = mountPage();
    await flushPromises();
    expect(apiMocks.listTeamEmployees).not.toHaveBeenCalled();

    switchTab("self-tab-team");
    await flushPromises();

    expect(apiMocks.listTeamEmployees).toHaveBeenCalledWith({ page: 1, page_size: 10 });
    expect(apiMocks.getOrgTree).toHaveBeenCalledTimes(1);
    const table = document.querySelector('[data-testid="self-team-table"]')?.textContent ?? "";
    expect(table).toContain("EMP001");
    expect(table).toContain("研发部");
    expect(table).toContain("市场部");
    wrapper.unmount();
  });

  it("我的目标页签懒加载按周期分组，active 周期可更新进度", async () => {
    const wrapper = mountPage();
    await flushPromises();
    expect(apiMocks.getMyGoals).not.toHaveBeenCalled();

    switchTab("self-tab-goals");
    await flushPromises();

    expect(apiMocks.getMyGoals).toHaveBeenCalledTimes(1);
    const active = document.querySelector('[data-testid="self-goal-cycle-cyc-1"]')?.textContent ?? "";
    expect(active).toContain("2026-H1");
    expect(active).toContain("交付达成");
    expect(document.querySelector('[data-testid="self-goal-save-goal-1"]')).not.toBeNull();

    const closed = document.querySelector('[data-testid="self-goal-cycle-cyc-0"]')?.textContent ?? "";
    expect(closed).toContain("质量提升");
    expect(document.querySelector('[data-testid="self-goal-save-goal-0"]')).toBeNull();

    setInputValue("self-goal-progress-goal-1", "90");
    setInputValue("self-goal-actual-goal-1", "9/10");
    clickButton("self-goal-save-goal-1");
    await flushPromises();

    expect(apiMocks.updateMyGoalProgress).toHaveBeenCalledWith("goal-1", {
      progress: 90,
      actual_value: "9/10",
    });
    expect(apiMocks.getMyGoals).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });

  it("我的绩效页签懒加载，收口周期展示最终评级与系数", async () => {
    const wrapper = mountPage();
    await flushPromises();
    expect(apiMocks.getMyReviews).not.toHaveBeenCalled();

    switchTab("self-tab-reviews");
    await flushPromises();

    expect(apiMocks.getMyReviews).toHaveBeenCalledTimes(1);
    const closed = document.querySelector('[data-testid="self-review-rev-0"]')?.textContent ?? "";
    expect(closed).toContain("2025-H2");
    expect(closed).toContain("A");
    expect(closed).toContain("1.2");

    const pending = document.querySelector('[data-testid="self-review-rev-1"]')?.textContent ?? "";
    expect(pending).toContain("2026-H1");
    wrapper.unmount();
  });

  it("申请变更弹窗预填 self_editable 属性，仅提交变更项", async () => {
    const wrapper = mountPage();
    await flushPromises();

    clickButton("self-change-request-open");
    await flushPromises();
    const modal = document.querySelector('[data-testid="self-change-request-modal"]');
    expect(modal?.textContent).toContain("家庭住址");

    setInputValue("self-change-title", "更新家庭住址");
    setInputValue("self-change-input-def-2", "海淀区");
    clickButton("self-change-submit");
    await flushPromises();

    expect(apiMocks.submitChangeRequest).toHaveBeenCalledTimes(1);
    const arg = apiMocks.submitChangeRequest.mock.calls[0][0];
    expect(arg.title).toBe("更新家庭住址");
    expect(arg.changes).toEqual([{ definition_id: "def-2", new_value: "海淀区" }]);
    wrapper.unmount();
  });

  it("未修改任何属性时提交变更被拦截", async () => {
    const wrapper = mountPage();
    await flushPromises();

    clickButton("self-change-request-open");
    await flushPromises();

    setInputValue("self-change-title", "无变更");
    clickButton("self-change-submit");
    await flushPromises();

    expect(apiMocks.submitChangeRequest).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("我的申请弹窗展示列表，pending 可撤销并刷新", async () => {
    const wrapper = mountPage();
    await flushPromises();
    expect(apiMocks.listMyChangeRequests).not.toHaveBeenCalled();

    clickButton("self-my-requests-open");
    await flushPromises();

    expect(apiMocks.listMyChangeRequests).toHaveBeenCalledWith({ page: 1, page_size: 50 });
    const table = document.querySelector('[data-testid="self-my-requests-table"]')?.textContent ?? "";
    expect(table).toContain("更新家庭住址");
    expect(table).toContain("待审批");
    expect(document.querySelector('[data-testid="self-request-cancel-ar-1"]')).not.toBeNull();

    clickButton("self-request-cancel-ar-1");
    await flushPromises();

    expect(apiMocks.cancelChangeRequest).toHaveBeenCalledWith("ar-1");
    expect(apiMocks.listMyChangeRequests).toHaveBeenCalledTimes(2);
    wrapper.unmount();
  });
});
