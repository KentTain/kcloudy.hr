/**
 * AnalyticsPage（报表分析）页面测试：人事域四卡+趋势/组织分布（树下钻/组织下钻）
 * + 离职风险名单、招聘域漏斗与渠道转化、薪酬域权限显隐、绩效域均分趋势与评级分布、
 * 真日期区间（DateInput）与下钻联动参数。
 * unovis 在 jsdom 挂不稳：mock @unovis/vue 底层组件（entityProfilerTab 先例）
 */
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DateInput } from "@/components";

import AnalyticsPage from "@/hr/pages/analytics/AnalyticsPage.vue";

vi.mock("@unovis/vue", () => ({
  VisXYContainer: { name: "VisXYContainer", props: ["data", "height", "margin", "padding"], template: "<div />" },
  VisAxis: { name: "VisAxis", props: ["type", "x", "y", "tickFormat", "gridLine", "tickTextFitMode", "numTicks"], template: "<div />" },
  VisLine: { name: "VisLine", props: ["x", "y", "color", "lineWidth"], template: "<div />" },
  VisCrosshair: { name: "VisCrosshair", props: ["template", "color", "x", "y", "hideWhenFarFromPointer"], template: "<div />" },
  VisTooltip: { name: "VisTooltip", props: ["horizontalShift"], template: "<div />" },
}));

const permState = vi.hoisted(() => ({
  granted: new Set<string>(["hr:report:read"]),
}));

const apiMocks = vi.hoisted(() => ({
  getReportOverview: vi.fn(),
  getReportTurnover: vi.fn(),
  getReportRecruiting: vi.fn(),
  getReportCompDist: vi.fn(),
  getReportPerformance: vi.fn(),
  getReportAttritionRisk: vi.fn(),
  exportReport: vi.fn(),
  getOrgTree: vi.fn(),
}));

vi.mock("@/hr/api/report", () => ({
  getReportOverview: apiMocks.getReportOverview,
  getReportTurnover: apiMocks.getReportTurnover,
  getReportRecruiting: apiMocks.getReportRecruiting,
  getReportCompDist: apiMocks.getReportCompDist,
  getReportPerformance: apiMocks.getReportPerformance,
  getReportAttritionRisk: apiMocks.getReportAttritionRisk,
  exportReport: apiMocks.exportReport,
  askReport: vi.fn(),
}));

const downloadMocks = vi.hoisted(() => ({
  downloadBase64File: vi.fn(),
}));

vi.mock("@/hr/utils/download", () => ({
  downloadBase64File: downloadMocks.downloadBase64File,
}));

vi.mock("@/hr/api/reference", () => ({
  getOrgTree: apiMocks.getOrgTree,
  getPositionOptions: vi.fn(),
  listEmployeeSalaryPackages: vi.fn(),
  getBandComparison: vi.fn(),
  listSalaryItemOptions: vi.fn(),
}));

vi.mock("@/framework/stores", () => ({
  useUserStore: () => ({
    hasPermission: (code: string) => permState.granted.has(code),
  }),
}));

const OVERVIEW = {
  cards: { active_count: 120, probation_count: 8, month_hired_count: 3, turnover_rate: 0.035 },
  headcount_trend: [
    { month: "2026-08", count: 110 },
    { month: "2026-09", count: 115 },
    { month: "2026-10", count: 120 },
  ],
  org_distribution: [
    { org_id: "org-1", count: 10 },
    { org_id: "org-11", count: 30 },
    { org_id: "org-12", count: 5 },
    { org_id: "org-2", count: 7 },
    { org_id: null, count: 2 },
  ],
  metric_ref: {
    metric: "headcount_gap",
    display_name: "编制缺口",
    description: "在编人数与编制数的差额，随人事总览实时计算",
    source: "ontology",
  },
};

const TURNOVER = {
  points: [
    { month: "2026-09", offboarded: 1, avg_headcount: 100, rate: 1.0 },
    { month: "2026-10", offboarded: 0, avg_headcount: 118, rate: null },
  ],
};

const RECRUITING = {
  funnel: [
    { stage: "pending_screening", count: 40 },
    { stage: "screening_passed", count: 20 },
    { stage: "interviewing", count: 10 },
    { stage: "onboarded", count: 2 },
  ],
  channels: [
    { channel: "manual", stages: { pending_screening: 10, onboarded: 1 } },
    { channel: "referral", stages: { pending_screening: 6, interviewing: 2 } },
  ],
};

const RISK = {
  total: 3,
  items: [
    {
      employee_id: "e1",
      employee_no: "E001",
      name: "张三",
      org_id: "org-1",
      score: 65,
      level: "high",
      factors: ["薪酬低于职级薪带下限", "近90天考勤异常≥3次"],
    },
    {
      employee_id: "e2",
      employee_no: "E002",
      name: "李四",
      org_id: null,
      score: 15,
      level: "low",
      factors: ["近180天无异动且司龄≥2年"],
    },
  ],
};

const COMP_DIST = {
  by_level: [
    { key: "P5", count: 12, min_amount: 10000, mid_amount: 15000, max_amount: 20000 },
    { key: null, count: 3, min_amount: 8000, mid_amount: 9000, max_amount: 10000 },
  ],
  by_org: [{ key: "org-1", count: 15, min_amount: 9000, mid_amount: 14000, max_amount: 22000 }],
};

const PERFORMANCE = {
  cycles: [
    {
      cycle_id: "cyc-1",
      cycle_name: "2026-H1",
      end_date: "2026-06-30",
      total: 3,
      avg_score: 85,
      ratings: { S: 1, A: 1, B: 1 },
    },
    {
      cycle_id: "cyc-2",
      cycle_name: "2026-H2",
      end_date: "2026-12-31",
      total: 2,
      avg_score: null,
      ratings: { A: 2 },
    },
  ],
  metric_ref: {
    metric: "perf_rating_distribution",
    display_name: "绩效评级分布",
    description: "closed 周期最终评级的人数分布",
    source: "builtin",
  },
};

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
  { id: "org-2", name: "分公司", parent_id: null, children: [] },
];

function mountPage(): VueWrapper {
  return mount(AnalyticsPage, { attachTo: document.body });
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

beforeEach(() => {
  vi.resetAllMocks();
  permState.granted = new Set(["hr:report:read"]);
  apiMocks.getReportOverview.mockResolvedValue({ code: 200, data: OVERVIEW });
  apiMocks.getReportTurnover.mockResolvedValue({ code: 200, data: TURNOVER });
  apiMocks.getReportRecruiting.mockResolvedValue({ code: 200, data: RECRUITING });
  apiMocks.getReportCompDist.mockResolvedValue({ code: 200, data: COMP_DIST });
  apiMocks.getReportPerformance.mockResolvedValue({ code: 200, data: PERFORMANCE });
  apiMocks.getReportAttritionRisk.mockResolvedValue({ code: 200, data: RISK });
  apiMocks.getOrgTree.mockResolvedValue({ code: 200, data: ORG_TREE });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("AnalyticsPage", () => {
  it("人事域默认加载四统计卡与组织分布（一级含子树合计），参数为默认真日期区间", async () => {
    const wrapper = mountPage();
    await flushPromises();

    expect(apiMocks.getReportOverview).toHaveBeenCalledTimes(1);
    const params = apiMocks.getReportOverview.mock.calls[0][0] as {
      date_from: string;
      date_to: string;
      org_id?: string;
    };
    expect(params.date_from).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(params.date_to).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(params.org_id).toBeUndefined();
    expect(apiMocks.getReportTurnover).toHaveBeenCalledWith(params);

    const cards = document.querySelector('[data-testid="report-personnel-cards"]')?.textContent ?? "";
    expect(cards).toContain("120");
    expect(cards).toContain("3.5%");

    // 一级行：总部 = 10+30+5 = 45
    const orgRow = document.querySelector('[data-testid="report-org-row-org-1"]')?.textContent ?? "";
    expect(orgRow).toContain("总部");
    expect(orgRow).toContain("45");
    // 子组织行未展开不出现
    expect(document.querySelector('[data-testid="report-org-row-org-11"]')).toBeNull();
    expect(document.querySelector('[data-testid="report-org-row-__none__"]')?.textContent).toContain("2");

    const chart = wrapper.findComponent({ name: "TrendLineChart" });
    expect(chart.exists()).toBe(true);
    wrapper.unmount();
  });

  it("指标口径行随响应渲染：来源徽标区分治理目录与内置口径", async () => {
    mountPage();
    await flushPromises();

    const headRef = document.querySelector('[data-testid="report-metric-ref-headcount"]')?.textContent ?? "";
    expect(headRef).toContain("口径 · 编制缺口");
    expect(headRef).toContain("在编人数与编制数的差额，随人事总览实时计算");
    expect(headRef).toContain("治理目录");

    switchTab("report-tab-performance");
    await flushPromises();

    const perfRef = document.querySelector('[data-testid="report-metric-ref-perf"]')?.textContent ?? "";
    expect(perfRef).toContain("口径 · 绩效评级分布");
    expect(perfRef).toContain("closed 周期最终评级的人数分布");
    expect(perfRef).toContain("内置口径");
  });

  it("人事域渲染离职风险名单（等级 Badge + 因子标签 + 组织名）", async () => {
    mountPage();
    await flushPromises();

    expect(apiMocks.getReportAttritionRisk).toHaveBeenCalledTimes(1);
    expect(apiMocks.getReportAttritionRisk).toHaveBeenCalledWith({ org_id: undefined, limit: 20 });
    const panel = document.querySelector('[data-testid="report-risk-panel"]')?.textContent ?? "";
    expect(panel).toContain("离职风险名单");
    expect(panel).toContain("张三（E001）");
    expect(panel).toContain("总部");
    expect(panel).toContain("高风险 65");
    expect(panel).toContain("薪酬低于职级薪带下限");
    expect(panel).toContain("近90天考勤异常≥3次");
    expect(panel).toContain("李四（E002）");
    expect(panel).toContain("低风险 15");
    expect(panel).toContain("未分配组织");
  });

  it("组织分布点击展开二级（各自子树合计），再点收起", async () => {
    mountPage();
    await flushPromises();

    clickButton("report-org-toggle-org-1");
    await flushPromises();

    expect(document.querySelector('[data-testid="report-org-row-org-11"]')?.textContent).toContain("30");
    expect(document.querySelector('[data-testid="report-org-row-org-12"]')?.textContent).toContain("5");

    clickButton("report-org-toggle-org-1");
    await flushPromises();
    expect(document.querySelector('[data-testid="report-org-row-org-11"]')).toBeNull();
  });

  it("组织行点击下钻：人事/风险带 org_id 重拉，chip 显示组织名并可恢复全组织", async () => {
    mountPage();
    await flushPromises();
    expect(apiMocks.getReportOverview).toHaveBeenCalledTimes(1);

    clickButton("report-org-drill-org-1");
    await flushPromises();

    expect(apiMocks.getReportOverview).toHaveBeenCalledTimes(2);
    expect(apiMocks.getReportOverview).toHaveBeenLastCalledWith(expect.objectContaining({ org_id: "org-1" }));
    expect(apiMocks.getReportTurnover).toHaveBeenLastCalledWith(expect.objectContaining({ org_id: "org-1" }));
    expect(apiMocks.getReportAttritionRisk).toHaveBeenLastCalledWith({ org_id: "org-1", limit: 20 });
    const chip = document.querySelector('[data-testid="report-drill-chip"]');
    expect(chip?.textContent).toContain("总部");

    clickButton("report-drill-chip");
    await flushPromises();
    expect(apiMocks.getReportOverview).toHaveBeenCalledTimes(3);
    const resetParams = apiMocks.getReportOverview.mock.calls[2][0] as { org_id?: string };
    expect(resetParams.org_id).toBeUndefined();
    expect(document.querySelector('[data-testid="report-drill-chip"]')).toBeNull();
  });

  it("招聘域漏斗与渠道转化渲染，参数为真日期区间对象", async () => {
    mountPage();
    await flushPromises();

    switchTab("report-tab-recruiting");
    await flushPromises();

    expect(apiMocks.getReportRecruiting).toHaveBeenCalledTimes(1);
    const params = apiMocks.getReportRecruiting.mock.calls[0][0] as {
      date_from: string;
      date_to: string;
      org_id?: string;
    };
    expect(params.date_from).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(params.date_to).toMatch(/^\d{4}-\d{2}-\d{2}$/);

    const funnel = document.querySelector('[data-testid="report-funnel"]')?.textContent ?? "";
    expect(funnel).toContain("待初筛");
    expect(funnel).toContain("40");
    expect(funnel).toContain("已入职");

    const channels = document.querySelector('[data-testid="report-channels"]')?.textContent ?? "";
    // manual 渠道录用段合计=onboarded 1/总 11
    expect(channels).toContain("录用 1/11（9.1%）");
    // referral 渠道无录用：0.0%
    expect(channels).toContain("0/8（0.0%）");
  });

  it("薪酬页签无权限隐藏，有权限时显示并加载脱敏分布", async () => {
    const first = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="report-tab-compensation"]')).toBeNull();
    expect(document.querySelector('[data-testid="report-tab-performance"]')).toBeTruthy();
    // 未经薪酬域不触发 comp-dist
    expect(apiMocks.getReportCompDist).not.toHaveBeenCalled();
    first.unmount();
    document.body.innerHTML = "";

    permState.granted = new Set(["hr:report:read", "hr:salary_package:read"]);
    const wrapper = mountPage();
    await flushPromises();
    switchTab("report-tab-compensation");
    await flushPromises();

    expect(apiMocks.getReportCompDist).toHaveBeenCalledTimes(1);
    const level = document.querySelector('[data-testid="report-comp-level"]')?.textContent ?? "";
    expect(level).toContain("P5");
    expect(level).toContain("未定级");
    expect(level).toContain("15,000");
    const orgDist = document.querySelector('[data-testid="report-comp-org"]')?.textContent ?? "";
    expect(orgDist).toContain("总部");
    // 同一实例内切走再切回不重复请求（comp-dist 与区间无关，只拉一次）
    switchTab("report-tab-personnel");
    await flushPromises();
    switchTab("report-tab-compensation");
    await flushPromises();
    expect(apiMocks.getReportCompDist).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("绩效页签加载周期均分趋势与评级分布（最终评级优先）", async () => {
    mountPage();
    await flushPromises();
    const calls = apiMocks.getReportOverview.mock.calls.length;

    switchTab("report-tab-performance");
    await flushPromises();

    expect(apiMocks.getReportPerformance).toHaveBeenCalledTimes(1);
    expect(apiMocks.getReportOverview.mock.calls.length).toBe(calls);
    const body = document.body.textContent ?? "";
    expect(body).toContain("周期均分趋势");
    expect(body).toContain("2026-H1");
    // 评级分布：H1 周期 S/A/B 各 1 人、H2 仅 A 2 人
    expect(document.querySelector('[data-testid="report-perf-cycle-cyc-1"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="report-perf-cycle-cyc-2"]')).toBeTruthy();
    expect(body).toContain("共 3 人");
    expect(body).toContain("共 2 人");
  });

  it("绩效页签首次加载后缓存，再切回不重复请求", async () => {
    const wrapper = mountPage();
    await flushPromises();

    switchTab("report-tab-performance");
    await flushPromises();
    expect(apiMocks.getReportPerformance).toHaveBeenCalledTimes(1);

    switchTab("report-tab-personnel");
    await flushPromises();
    switchTab("report-tab-performance");
    await flushPromises();
    expect(apiMocks.getReportPerformance).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });

  it("开始日期变更后人事域以新区间重拉", async () => {
    const wrapper = mountPage();
    await flushPromises();
    expect(apiMocks.getReportOverview).toHaveBeenCalledTimes(1);

    // DateInput 经组件实例驱动 v-model（reka 弹层在 jsdom 中不展开）
    const dateInput = wrapper.findComponent(DateInput);
    dateInput.vm.$emit("update:modelValue", "2026-01-01");
    await flushPromises();

    expect(apiMocks.getReportOverview).toHaveBeenCalledTimes(2);
    const params = apiMocks.getReportOverview.mock.calls[1][0] as { date_from: string };
    expect(params.date_from).toBe("2026-01-01");
    wrapper.unmount();
  });

  it("报表导出：有导出权限出项，点击按当前域与区间调用并下载文件", async () => {
    permState.granted = new Set(["hr:report:read", "hr:report:export"]);
    apiMocks.exportReport.mockResolvedValue({
      code: 200,
      data: { filename: "报表导出-overview-2026.xlsx", content_base64: "AAAA" },
    });
    mountPage();
    await flushPromises();

    expect(document.querySelector('[data-testid="report-export"]')).toBeTruthy();
    clickButton("report-export");
    await flushPromises();

    expect(apiMocks.exportReport).toHaveBeenCalledTimes(1);
    expect(apiMocks.exportReport).toHaveBeenCalledWith(
      expect.objectContaining({ domain: "overview", org_id: undefined }),
    );
    expect(downloadMocks.downloadBase64File).toHaveBeenCalledWith("报表导出-overview-2026.xlsx", "AAAA");
  });

  it("报表导出按钮随 hr:report:export 权限显隐", async () => {
    mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="report-export"]')).toBeNull();
    expect(apiMocks.exportReport).not.toHaveBeenCalled();
  });
});
