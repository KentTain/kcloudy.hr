<script setup lang="ts">
/**
 * 周期概览抽屉：周期信息 + 目标列表 + 评级分布直方图（校准参考）+ 状态操作区。
 * 评估明细列表随评估管理批次（批 C）补齐，本期先出分布聚合。
 */
import { computed, ref, watch } from "vue";

import { Badge, Button, Table } from "@/components";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

import { useUserStore } from "@/framework/stores";
import { getErrorMessage, notifyError } from "@/framework/utils/feedback";

import { getPerfDistribution, listPerfGoals } from "@/hr/api/perf";
import {
  PERF_CYCLE_STATUS_LABELS,
  PERF_CYCLE_STATUS_VARIANTS,
  PERF_GOAL_STATUS_LABELS,
  PERF_RATINGS,
  PERF_TRANSITION_LABELS,
  PERF_TRANSITIONS,
  type PerfCycleItem,
  type PerfCycleStatus,
  type PerfDistribution,
  type PerfGoalItem,
  type PerfGoalStatus,
} from "@/hr/types/perf";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  cycle: PerfCycleItem | null;
}>();

const emit = defineEmits<{ transition: [action: string] }>();

const userStore = useUserStore();
const canWrite = computed(() => userStore.hasPermission("hr:perf_cycle:write"));

const loading = ref(false);
const goals = ref<PerfGoalItem[]>([]);
const distribution = ref<PerfDistribution | null>(null);

const goalColumns = [
  { key: "employee_name", title: "负责人", width: "100px" },
  { key: "code", title: "编码", width: "90px" },
  { key: "name", title: "目标名称", width: "160px" },
  { key: "weight", title: "权重", width: "80px" },
  { key: "progress", title: "进度", width: "80px" },
  { key: "status", title: "状态", width: "80px" },
];

const nextActions = computed(() => {
  if (!props.cycle) return [];
  return PERF_TRANSITIONS[props.cycle.status as PerfCycleStatus] ?? [];
});

watch(open, async (value) => {
  if (!value || !props.cycle) return;
  goals.value = [];
  distribution.value = null;
  loading.value = true;
  try {
    const [goalsRes, distRes] = await Promise.all([
      listPerfGoals({ page: 1, page_size: 100, cycle_id: props.cycle.id }),
      getPerfDistribution(props.cycle.id),
    ]);
    goals.value = goalsRes.data ?? [];
    distribution.value = distRes.data ?? null;
  } catch (error) {
    notifyError(error, getErrorMessage(error, "周期概览加载失败"));
  } finally {
    loading.value = false;
  }
});

function maxCount(): number {
  if (!distribution.value) return 0;
  return Math.max(1, ...Object.values(distribution.value.ratings).map((item) => item.count));
}
</script>

<template>
  <Sheet :open="open" @update:open="open = $event">
    <SheetContent side="right" class="flex w-full flex-col gap-0 sm:max-w-3xl" data-testid="cycle-overview-drawer">
      <SheetHeader class="shrink-0 border-b px-5 py-4">
        <SheetTitle class="flex items-center gap-2" data-testid="cycle-overview-title">
          {{ cycle?.name ?? "--" }}
          <Badge
            v-if="cycle"
            :variant="PERF_CYCLE_STATUS_VARIANTS[cycle.status as PerfCycleStatus]"
          >
            {{ PERF_CYCLE_STATUS_LABELS[cycle.status as PerfCycleStatus] }}
          </Badge>
        </SheetTitle>
        <SheetDescription class="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          <span>起止：{{ cycle?.start_date }} ~ {{ cycle?.end_date }}</span>
          <span>目标：{{ cycle?.goal_count ?? 0 }} 项</span>
          <span>评估：{{ cycle?.review_count ?? 0 }} 份</span>
        </SheetDescription>
      </SheetHeader>

      <div class="flex min-h-0 flex-1 flex-col gap-5 overflow-auto px-5 py-4">
        <section class="flex flex-col gap-2">
          <h3 class="text-sm font-medium">目标列表</h3>
          <Table
            :columns="goalColumns"
            :data="goals"
            :loading="loading"
            empty-text="该周期暂无目标"
            data-testid="cycle-goals-table"
          >
            <template #weight="{ row }">
              {{ (row as PerfGoalItem).weight }}%
            </template>
            <template #progress="{ row }">
              {{ (row as PerfGoalItem).progress }}%
            </template>
            <template #status="{ row }">
              <Badge variant="secondary">
                {{ PERF_GOAL_STATUS_LABELS[(row as PerfGoalItem).status as PerfGoalStatus] }}
              </Badge>
            </template>
          </Table>
        </section>

        <section class="flex flex-col gap-2">
          <h3 class="text-sm font-medium">评级分布（校准参考）</h3>
          <div
            v-if="distribution"
            class="flex flex-col gap-2"
            data-testid="cycle-distribution"
          >
            <div
              v-for="rating in PERF_RATINGS"
              :key="rating"
              class="flex items-center gap-3 text-xs"
              :data-testid="`distribution-${rating}`"
            >
              <span class="w-6 font-medium">{{ rating }}</span>
              <div class="bg-muted h-4 flex-1 overflow-hidden rounded">
                <div
                  class="bg-primary h-full rounded"
                  :style="{
                    width: `${((distribution.ratings[rating]?.count ?? 0) / maxCount()) * 100}%`,
                  }"
                />
              </div>
              <span class="w-24 text-right text-muted-foreground">
                {{ distribution.ratings[rating]?.count ?? 0 }} 人（{{ distribution.ratings[rating]?.percent ?? 0 }}%）
              </span>
            </div>
          </div>
          <p v-else class="text-muted-foreground text-xs">加载中…</p>
        </section>
      </div>

      <div
        v-if="cycle && canWrite && nextActions.length"
        class="shrink-0 border-t px-5 py-3"
        data-testid="cycle-overview-actions"
      >
        <div class="flex items-center gap-2">
          <Button
            v-for="action in nextActions"
            :key="action"
            size="sm"
            :variant="action === 'close' ? 'destructive' : 'outline'"
            :data-testid="`cycle-overview-${action}`"
            @click="emit('transition', action)"
          >
            {{ PERF_TRANSITION_LABELS[action] }}
          </Button>
        </div>
      </div>
    </SheetContent>
  </Sheet>
</template>
