/**
 * FunnelBar 三段漏斗单元测试：分段渲染与合计、阶段计数、点击选中/取消联动 emit
 */
import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";

import FunnelBar from "@/hr/components/recruiting/FunnelBar.vue";
import type { FunnelStat } from "@/hr/types/recruiting";

const STATS: FunnelStat[] = [
  { stage: "pending_screening", count: 5 },
  { stage: "screening_passed", count: 3 },
  { stage: "interviewing", count: 2 },
  { stage: "pre_hire", count: 1 },
  { stage: "onboarded", count: 1 },
];

afterEach(() => {
  document.body.innerHTML = "";
});

describe("FunnelBar", () => {
  it("渲染三段漏斗（初筛/面试/录用）与各阶段计数", () => {
    const wrapper = mount(FunnelBar, { props: { stats: STATS }, attachTo: document.body });

    expect(wrapper.find('[data-testid="funnel-bar"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="funnel-segment-screening"]').text()).toContain("初筛");
    expect(wrapper.find('[data-testid="funnel-segment-interview"]').text()).toContain("面试");
    expect(wrapper.find('[data-testid="funnel-segment-hire"]').text()).toContain("录用");

    // 段合计：初筛 5+3=8、面试 2、录用 1+1=2
    expect(wrapper.find('[data-testid="funnel-segment-screening"]').text()).toContain("8");
    expect(wrapper.find('[data-testid="funnel-segment-interview"]').text()).toContain("2");
    expect(wrapper.find('[data-testid="funnel-stage-pending_screening"]').text()).toContain("5");
    // 结果态不入漏斗段（rejected/withdrawn/onboard_abandoned）
    expect(wrapper.find('[data-testid="funnel-stage-rejected"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("点击阶段 emit stageSelect；同阶段再点取消（emit 空串）", async () => {
    const wrapper = mount(FunnelBar, { props: { stats: STATS }, attachTo: document.body });

    await wrapper.find('[data-testid="funnel-stage-interviewing"]').trigger("click");
    expect(wrapper.emitted("stageSelect")?.at(-1)).toEqual(["interviewing"]);

    // selected 联动高亮后，同阶段再点 → 取消
    await wrapper.setProps({ selected: "interviewing" });
    await wrapper.find('[data-testid="funnel-stage-interviewing"]').trigger("click");
    expect(wrapper.emitted("stageSelect")?.at(-1)).toEqual([""]);
    wrapper.unmount();
  });

  it("无数据显示零计数的三段空漏斗", () => {
    const wrapper = mount(FunnelBar, { props: { stats: [] }, attachTo: document.body });

    expect(wrapper.find('[data-testid="funnel-stage-pending_screening"]').text()).toContain("0");
    expect(wrapper.find('[data-testid="funnel-segment-hire"]').text()).toContain("0");
    wrapper.unmount();
  });
});
