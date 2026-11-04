<script setup lang="ts">
import { computed } from "vue";

import {
  ChartAxis,
  type ChartConfig,
  ChartContainer,
  ChartCrosshair,
  ChartLine,
  ChartTooltip,
  ChartTooltipContent,
  ChartXYContainer,
  componentToString,
} from "@/components/ui/chart";

const props = withDefaults(
  defineProps<{
    points: { label: string; value: number }[];
    color?: string;
    valueSuffix?: string;
    height?: number;
  }>(),
  {
    color: "#2563eb",
    valueSuffix: "",
    height: 240,
  },
);

interface ChartDatum {
  label: string;
  idx: number;
  value: number;
}

const hasData = computed(() => props.points.length > 0);

const chartConfig = computed<ChartConfig>(() => ({
  value: { color: props.color, label: props.valueSuffix ? `数值${props.valueSuffix}` : "数值" },
}));

const chartData = computed<ChartDatum[]>(() =>
  props.points.map((point, index) => ({ label: point.label, idx: index, value: Number(point.value ?? 0) })),
);

function getX(point: ChartDatum): number {
  return point.idx;
}

function getY(point: ChartDatum): number {
  return point.value;
}

const yAccessors = computed(() => [(point: ChartDatum) => getY(point)]);

function getSeriesColor(): string {
  return props.color;
}

function formatTick(value: number | Date): string {
  return chartData.value.find((point) => point.idx === Number(value))?.label ?? "";
}

function formatValue(value: number): string {
  const numeric = Number(value ?? 0);
  const text = Number.isInteger(numeric) ? numeric.toLocaleString("zh-CN") : numeric.toFixed(2);
  return props.valueSuffix ? `${text}${props.valueSuffix}` : text;
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col" :style="{ height: `${height}px` }">
    <div v-if="!hasData" class="flex flex-1 items-center justify-center text-sm text-muted-foreground">暂无数据</div>
    <ChartContainer v-else class="h-full min-h-0 w-full" cursor :config="chartConfig">
      <ChartXYContainer :data="chartData" :padding="{ bottom: 24, left: 8, right: 8, top: 8 }">
        <ChartAxis type="x" :grid-line="false" :tick-format="formatTick" :tick-text-fit-mode="'trim'" :x="getX" />
        <ChartAxis type="y" :tick-format="formatValue" :y="getY" />
        <ChartLine :color="getSeriesColor" :line-width="3" :x="getX" :y="yAccessors" />
        <ChartTooltip :horizontal-shift="8" />
        <ChartCrosshair
          :color="getSeriesColor"
          :hide-when-far-from-pointer="false"
          :template="componentToString(chartConfig, ChartTooltipContent, { valueFormatter: formatValue })"
          :x="getX"
          :y="yAccessors" />
      </ChartXYContainer>
    </ChartContainer>
  </div>
</template>
