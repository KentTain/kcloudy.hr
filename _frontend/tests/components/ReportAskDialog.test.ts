/**
 * ReportAskDialog（NL 问数弹窗）测试：提问成功展示回答/指标/口径、
 * 白名单越界 400 展示错误提示、空提问按钮禁用
 */
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ReportAskDialog from "@/hr/components/report/ReportAskDialog.vue";
import type { ReportAskData } from "@/hr/types/report";

const apiMocks = vi.hoisted(() => ({
  askReport: vi.fn(),
}));

vi.mock("@/hr/api/report", () => ({
  askReport: apiMocks.askReport,
}));

vi.mock("@/framework/utils/feedback", () => ({
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

function makeAskData(overrides: Partial<ReportAskData> = {}): ReportAskData {
  return {
    metric: "离职率",
    domain: "personnel",
    metric_ref: "离职率 = 当月离职人数 / 当月平均在编（月初+月末均值），百分数",
    source: "keyword",
    data: { points: [{ month: "2026-09", offboarded: 1, avg_headcount: 100, rate: 1.0 }] },
    answer: "近月离职率 1.0%。",
    ...overrides,
  };
}

function mountDialog(open = true): VueWrapper {
  return mount(ReportAskDialog, {
    props: { open },
    attachTo: document.body,
  });
}

function clickButton(testid: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  if (el instanceof HTMLElement) el.click();
}

async function typeQuestion(wrapper: VueWrapper, text: string) {
  // Dialog 内容 teleport 到 body：用 document 查询；common Input 的
  // data-testid 落根 div，原生 input 在内层；输值后 flush 解除按钮禁用
  const input = document.querySelector<HTMLInputElement>('[data-testid="report-ask-input"] input');
  if (!input) throw new Error("ask input not found");
  input.value = text;
  input.dispatchEvent(new Event("input"));
  await flushPromises();
}

beforeEach(() => {
  vi.resetAllMocks();
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("ReportAskDialog", () => {
  it("提问成功展示回答、指标徽标与口径说明", async () => {
    apiMocks.askReport.mockResolvedValue({ code: 200, data: makeAskData() });
    const wrapper = mountDialog();
    await flushPromises();

    await typeQuestion(wrapper, "最近 3 个月离职率如何");
    clickButton("report-ask-submit");
    await flushPromises();

    expect(apiMocks.askReport).toHaveBeenCalledWith("最近 3 个月离职率如何");
    expect(document.querySelector('[data-testid="report-ask-answer"]')?.textContent).toContain(
      "近月离职率 1.0%",
    );
    expect(document.querySelector('[data-testid="report-ask-metric"]')?.textContent).toContain("离职率");
    expect(document.querySelector('[data-testid="report-ask-ref"]')?.textContent).toContain(
      "当月离职人数",
    );
    wrapper.unmount();
  });

  it("白名单越界展示后端 400 错误提示", async () => {
    apiMocks.askReport.mockRejectedValue(new Error("bad request"));
    const wrapper = mountDialog();
    await flushPromises();

    await typeQuestion(wrapper, "每个人的工资是多少");
    clickButton("report-ask-submit");
    await flushPromises();

    expect(
      document.querySelector('[data-testid="report-ask-error"]')?.textContent,
    ).toContain("问数失败");
    expect(document.querySelector('[data-testid="report-ask-result"]')).toBeNull();
    wrapper.unmount();
  });

  it("空提问时按钮禁用", async () => {
    const wrapper = mountDialog();
    await flushPromises();
    const button = document.querySelector<HTMLButtonElement>('[data-testid="report-ask-submit"]');
    expect(button?.disabled).toBe(true);
    expect(apiMocks.askReport).not.toHaveBeenCalled();
    wrapper.unmount();
  });
});
