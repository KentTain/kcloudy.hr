<script setup lang="ts">
/**
 * 候选人卡片：投递申请聚合展示，操作随阶段出项（状态机）。
 * 特殊流转：安排面试（screening_passed）/发起 Offer（pre_hire）弹窗承载；
 * offered/pre_onboard 阶段经 Offer 状态机（接受/拒绝/办理入职），
 * 其余直接按 STAGE_TRANSITIONS 渲染流转按钮；无匹配操作不显示操作区。
 */
import { computed } from "vue";

import { Badge, Button } from "@/components";

import {
  APPLICATION_STAGE_LABELS,
  APPLICATION_STAGE_VARIANTS,
  STAGE_TRANSITIONS,
  type Application,
  type ApplicationStage,
} from "@/hr/types/recruiting";

const props = defineProps<{
  application: Application;
  canWrite: boolean;
  canInterview: boolean;
  canOffer: boolean;
}>();

const emit = defineEmits<{
  stage: [application: Application, target: ApplicationStage];
  interview: [application: Application];
  offer: [application: Application];
  "offer-accept": [application: Application];
  "offer-reject": [application: Application];
  onboard: [application: Application];
  detail: [application: Application];
}>();

/** Offer 状态机承载的流转目标：accept→pre_onboard、reject（offered 态）、onboard→onboarded */
const OFFER_FLOW_TARGETS: ReadonlySet<ApplicationStage> = new Set(["pre_onboard", "onboarded"]);

const directTransitions = computed<ApplicationStage[]>(() =>
  STAGE_TRANSITIONS[props.application.stage].filter((target) => {
    if (target === "interviewing" || target === "offered") return false;
    if (OFFER_FLOW_TARGETS.has(target)) return false;
    if (props.application.stage === "offered" && target === "rejected") return false;
    return true;
  }),
);

const showInterviewButton = computed(
  () => props.canWrite && props.canInterview && props.application.stage === "screening_passed",
);

const showOfferButton = computed(
  () => props.canWrite && props.canOffer && props.application.stage === "pre_hire",
);

const showOfferRespond = computed(
  () => props.canWrite && props.canOffer && props.application.stage === "offered",
);

const showOnboardButton = computed(
  () => props.canWrite && props.canOffer && props.application.stage === "pre_onboard",
);

const hasActions = computed(
  () =>
    props.canWrite &&
    (directTransitions.value.length > 0 ||
      showInterviewButton.value ||
      showOfferButton.value ||
      showOfferRespond.value ||
      showOnboardButton.value),
);

const lastHistory = computed(() => props.application.stage_history?.at(-1) ?? null);
</script>

<template>
  <div class="flex flex-col gap-3 rounded-lg border p-4" data-testid="candidate-card">
    <div class="flex items-start justify-between gap-2">
      <button
        type="button"
        class="text-left font-medium hover:underline"
        data-testid="candidate-card-name"
        @click="emit('detail', application)"
      >
        {{ application.candidate_name ?? "未知候选人" }}
      </button>
      <Badge :variant="APPLICATION_STAGE_VARIANTS[application.stage]" data-testid="candidate-card-stage">
        {{ APPLICATION_STAGE_LABELS[application.stage] ?? application.stage }}
      </Badge>
    </div>

    <div class="text-muted-foreground flex flex-col gap-1 text-xs">
      <span>需求：{{ application.requisition_title ?? "--" }}</span>
      <span>
        匹配分：{{ application.match_score === null ? "--" : application.match_score }}
        · 投递：{{ application.apply_time?.slice(0, 10) ?? "--" }}
      </span>
      <span v-if="lastHistory">
        最近流转：{{ APPLICATION_STAGE_LABELS[lastHistory.stage as ApplicationStage] ?? lastHistory.stage }}
        {{ lastHistory.operated_at?.slice(0, 10) }}
      </span>
    </div>

    <div v-if="hasActions" class="flex flex-wrap items-center gap-1 border-t pt-2">
      <Button
        v-if="showInterviewButton"
        variant="outline"
        size="sm"
        data-testid="card-arrange-interview"
        @click="emit('interview', application)"
      >
        安排面试
      </Button>
      <Button
        v-if="showOfferButton"
        variant="outline"
        size="sm"
        data-testid="card-create-offer"
        @click="emit('offer', application)"
      >
        发起 Offer
      </Button>
      <template v-if="showOfferRespond">
        <Button
          variant="outline"
          size="sm"
          data-testid="card-offer-accept"
          @click="emit('offer-accept', application)"
        >
          接受 Offer
        </Button>
        <Button
          variant="link"
          size="sm"
          class="text-destructive h-auto p-0"
          data-testid="card-offer-reject"
          @click="emit('offer-reject', application)"
        >
          拒绝 Offer
        </Button>
      </template>
      <Button
        v-if="showOnboardButton"
        variant="outline"
        size="sm"
        data-testid="card-onboard"
        @click="emit('onboard', application)"
      >
        办理入职
      </Button>
      <Button
        v-for="target in directTransitions"
        :key="target"
        variant="link"
        size="sm"
        class="h-auto p-0"
        :class="target === 'rejected' || target === 'withdrawn' || target === 'onboard_abandoned' ? 'text-destructive' : ''"
        :data-testid="`card-stage-${target}`"
        @click="emit('stage', application, target)"
      >
        {{ APPLICATION_STAGE_LABELS[target] }}
      </Button>
    </div>
  </div>
</template>
