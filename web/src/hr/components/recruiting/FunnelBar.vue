<script setup lang="ts">
/**
 * 三段式漏斗阶段条：初筛/面试/录用各阶段计数；点击阶段联动过滤下方列表。
 * 纯展示组件，需求详情与候选人页复用。
 */
import { computed } from "vue";

import {
  APPLICATION_STAGE_LABELS,
  FUNNEL_SEGMENTS,
  type ApplicationStage,
  type FunnelStat,
} from "@/hr/types/recruiting";

const props = defineProps<{
  stats: FunnelStat[];
  /** 当前选中的阶段（联动过滤高亮，空串=不过滤） */
  selected?: string;
}>();

const emit = defineEmits<{ stageSelect: [stage: ApplicationStage | ""] }>();

const countOf = (stage: ApplicationStage): number =>
  props.stats.find((item) => item.stage === stage)?.count ?? 0;

const segments = computed(() =>
  FUNNEL_SEGMENTS.map((segment) => ({
    ...segment,
    total: segment.stages.reduce((sum, stage) => sum + countOf(stage), 0),
    items: segment.stages.map((stage) => ({
      stage,
      label: APPLICATION_STAGE_LABELS[stage],
      count: countOf(stage),
    })),
  })),
);

function handleStageClick(stage: ApplicationStage) {
  emit("stageSelect", props.selected === stage ? "" : stage);
}
</script>

<template>
  <div class="flex flex-wrap gap-4" data-testid="funnel-bar">
    <div
      v-for="(segment, index) in segments"
      :key="segment.key"
      class="flex min-w-44 flex-1 flex-col gap-2 rounded-lg border p-3"
      :data-testid="`funnel-segment-${segment.key}`"
    >
      <div class="flex items-center justify-between">
        <span class="text-muted-foreground text-xs font-medium">
          段{{ index + 1 }} {{ segment.label }}
        </span>
        <span class="text-sm font-semibold">{{ segment.total }}</span>
      </div>
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="item in segment.items"
          :key="item.stage"
          type="button"
          class="hover:bg-accent rounded-md border px-2 py-1 text-xs transition-colors"
          :class="selected === item.stage ? 'bg-primary/10 border-primary text-primary' : ''"
          :data-testid="`funnel-stage-${item.stage}`"
          @click="handleStageClick(item.stage)"
        >
          {{ item.label }}
          <span class="ml-1 font-semibold">{{ item.count }}</span>
        </button>
      </div>
    </div>
  </div>
</template>
