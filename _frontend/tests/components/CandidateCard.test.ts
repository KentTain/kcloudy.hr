/**
 * CandidateCard 组件测试：基础信息渲染、操作随阶段出项（状态机）
 * 与权限门控、弹窗承载流转（面试/Offer）的 emit 语义
 */
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import CandidateCard from "@/hr/components/candidate/CandidateCard.vue";
import type { Application, ApplicationStage } from "@/hr/types/recruiting";

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

function mountCard(application: Application, permissions: Partial<Record<"write" | "interview" | "offer", boolean>> = {}) {
  return mount(CandidateCard, {
    props: {
      application,
      canWrite: permissions.write ?? true,
      canInterview: permissions.interview ?? true,
      canOffer: permissions.offer ?? true,
    },
  });
}

describe("CandidateCard", () => {
  it("渲染候选人基础信息与阶段标签", () => {
    const wrapper = mountCard(makeApplication());
    expect(wrapper.find('[data-testid="candidate-card-name"]').text()).toContain("张三");
    expect(wrapper.find('[data-testid="candidate-card-stage"]').text()).toContain("待初筛");
    expect(wrapper.text()).toContain("后端工程师");
    expect(wrapper.text()).toContain("82");
  });

  it("pending_screening 阶段出项直接流转按钮，点击 emit stage", async () => {
    const wrapper = mountCard(makeApplication());
    const passButton = wrapper.find('[data-testid="card-stage-screening_passed"]');
    expect(passButton.exists()).toBe(true);
    await passButton.trigger("click");
    expect(wrapper.emitted("stage")?.at(-1)?.[1]).toBe("screening_passed");
    expect(wrapper.find('[data-testid="card-arrange-interview"]').exists()).toBe(false);
  });

  it("screening_passed 阶段出项「安排面试」，interviewing 不再直接流转", async () => {
    const wrapper = mountCard(makeApplication({ stage: "screening_passed" }));
    const interviewButton = wrapper.find('[data-testid="card-arrange-interview"]');
    expect(interviewButton.exists()).toBe(true);
    expect(wrapper.find('[data-testid="card-stage-interviewing"]').exists()).toBe(false);
    await interviewButton.trigger("click");
    expect(wrapper.emitted("interview")).toBeTruthy();
  });

  it("pre_hire 阶段出项「发起 Offer」，offered 不再直接流转", async () => {
    const wrapper = mountCard(makeApplication({ stage: "pre_hire" }));
    const offerButton = wrapper.find('[data-testid="card-create-offer"]');
    expect(offerButton.exists()).toBe(true);
    expect(wrapper.find('[data-testid="card-stage-offered"]').exists()).toBe(false);
    await offerButton.trigger("click");
    expect(wrapper.emitted("offer")).toBeTruthy();
  });

  it("offered 阶段出「接受/拒绝 Offer」（Offer 状态机承载，不走裸流转）", async () => {
    const wrapper = mountCard(makeApplication({ stage: "offered" }));
    expect(wrapper.find('[data-testid="card-stage-pre_onboard"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="card-stage-rejected"]').exists()).toBe(false);

    await wrapper.find('[data-testid="card-offer-accept"]').trigger("click");
    expect((wrapper.emitted("offer-accept")?.at(-1)?.[0] as Application).id).toBe("app-1");
    await wrapper.find('[data-testid="card-offer-reject"]').trigger("click");
    expect(wrapper.emitted("offer-reject")).toBeTruthy();
  });

  it("pre_onboard 阶段出「办理入职」，onboarded 不再直接流转（onboard_abandoned 保留）", async () => {
    const wrapper = mountCard(makeApplication({ stage: "pre_onboard" }));
    expect(wrapper.find('[data-testid="card-onboard"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="card-stage-onboarded"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="card-stage-onboard_abandoned"]').exists()).toBe(true);

    await wrapper.find('[data-testid="card-onboard"]').trigger("click");
    expect((wrapper.emitted("onboard")?.at(-1)?.[0] as Application).id).toBe("app-1");
  });

  it("Offer 操作按钮受 hr:offer:write 权限门控", () => {
    const responded = mountCard(makeApplication({ stage: "offered" }), { offer: false });
    expect(responded.find('[data-testid="card-offer-accept"]').exists()).toBe(false);
    const onboard = mountCard(makeApplication({ stage: "pre_onboard" }), { offer: false });
    expect(onboard.find('[data-testid="card-onboard"]').exists()).toBe(false);
  });

  it("终态与无写权限均不渲染操作区", () => {
    const terminal = mountCard(makeApplication({ stage: "onboarded" }));
    expect(terminal.find('[data-testid="card-stage-rejected"]').exists()).toBe(false);

    const noPerm = mountCard(makeApplication(), { write: false });
    expect(noPerm.find('[data-testid="card-arrange-interview"]').exists()).toBe(false);
    expect(noPerm.find('[data-testid="card-stage-rejected"]').exists()).toBe(false);
  });

  it("点击姓名 emit detail（详情侧滑入口）", async () => {
    const wrapper = mountCard(makeApplication());
    await wrapper.find('[data-testid="candidate-card-name"]').trigger("click");
    const emitted = wrapper.emitted("detail")?.at(-1)?.[0] as Application | undefined;
    expect(emitted?.id).toBe("app-1");
  });

  it("展示最近流转摘要", () => {
    const wrapper = mountCard(
      makeApplication({
        stage: "interviewing" as ApplicationStage,
        stage_history: [
          { stage: "screening_passed", operator_id: null, operated_at: "2026-10-11T09:00:00", remark: null },
        ],
      }),
    );
    expect(wrapper.text()).toContain("初筛通过");
  });
});
