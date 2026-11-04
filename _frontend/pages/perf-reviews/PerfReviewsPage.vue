<script setup lang="ts">
/**
 * 评估管理页：绩效评估执行面。按周期筛选评估列表，评分中周期可评分（hr:perf_review:write）、
 * 校准中周期可校准（hr:perf:calibrate，意见必填留痕）；选中周期展示评级分布与强制分布
 * 规则线（校准参考）。发起评估批量圈选被评人（统一评估人）。
 */
import type { ColumnDef } from "@tanstack/vue-table";
import { computed, h, ref, watch } from "vue";

import {
  Badge,
  Button,
  DataTable,
  Select,
  useDataTable,
} from "@/components";
import AppPage from "@/framework/layouts/components/AppPage.vue";

import { useUserStore } from "@/framework/stores";
import {
  getErrorMessage,
  notifyError,
  notifySuccess,
} from "@/framework/utils/feedback";

import { getPerfDistribution, listPerfCycles, listPerfReviews } from "@/hr/api/perf";
import ReviewCalibrateModal from "@/hr/components/perf/ReviewCalibrateModal.vue";
import ReviewLaunchModal from "@/hr/components/perf/ReviewLaunchModal.vue";
import ReviewScoreModal from "@/hr/components/perf/ReviewScoreModal.vue";
import {
  PERF_CYCLE_STATUS_LABELS,
  PERF_RATINGS,
  type PerfCycleItem,
  type PerfDistribution,
  type PerfRating,
  type PerfReviewItem,
  type PerfReviewQuery,
  type PerfReviewStatus,
  PERF_REVIEW_STATUS_LABELS,
  PERF_REVIEW_STATUS_VARIANTS,
} from "@/hr/types/perf";

const userStore = useUserStore();
const canWrite = computed(() => userStore.hasPermission("hr:perf_review:write"));
const canCalibrate = computed(() => userStore.hasPermission("hr:perf:calibrate"));

const ALL = "__all__";

const cycleId = ref<string>(ALL);
const cycles = ref<PerfCycleItem[]>([]);
const status = ref<PerfReviewStatus | typeof ALL>(ALL);

const statusOptions = [
  { value: ALL, label: "全部状态" },
  ...(Object.keys(PERF_REVIEW_STATUS_LABELS) as PerfReviewStatus[]).map((value) => ({
    value,
    label: PERF_REVIEW_STATUS_LABELS[value],
  })),
];

/* ── 校准参考：选中周期的评级分布 + 规则线 ── */

const distribution = ref<PerfDistribution | null>(null);
const maxCount = computed(() => {
  if (!distribution.value) return 0;
  return Math.max(...PERF_RATINGS.map((rating) => distribution.value!.ratings[rating]?.count ?? 0), 1);
});

watch(cycleId, async (value) => {
  distribution.value = null;
  if (value === ALL) return;
  try {
    const res = await getPerfDistribution(value);
    distribution.value = res.data ?? null;
  } catch (error) {
    notifyError(error, getErrorMessage(error, "评级分布加载失败"));
  }
});

async function loadCycles() {
  try {
    const res = await listPerfCycles({ page: 1, page_size: 100 });
    cycles.value = res.data ?? [];
  } catch (error) {
    notifyError(error, getErrorMessage(error, "考核周期加载失败"));
  }
}

const cycleOptions = computed(() => [
  { value: ALL, label: "全部周期" },
  ...cycles.value.map((cycle) => ({
    value: cycle.id,
    label: `${cycle.name}（${PERF_CYCLE_STATUS_LABELS[cycle.status]}）`,
  })),
]);

function envelope<T>(res: { code: number; data?: T[] | null; msg?: string; page?: number; page_size?: number; total?: number }, page: number, pageSize: number) {
  return {
    code: res.code,
    data: res.data ?? [],
    msg: res.msg,
    page: res.page || page,
    page_size: res.page_size || pageSize,
    total: res.total || 0,
  };
}

const columns = ref<ColumnDef<PerfReviewItem>[]>([
  {
    id: "employee",
    header: "被评人",
    size: 140,
    cell: ({ row }) =>
      `${row.original.employee_name ?? ""}（${row.original.employee_no ?? ""}）`,
  },
  { accessorKey: "reviewer_name", header: "评估人", size: 110 },
  {
    id: "goal_summary",
    header: "目标达成",
    size: 110,
    cell: ({ row }) =>
      `${row.original.goal_count} 项目标 · 加权进度 ${row.original.weighted_progress}%`,
  },
  { accessorKey: "self_score", header: "自评", size: 80 },
  { accessorKey: "score", header: "得分", size: 80 },
  {
    accessorKey: "rating",
    header: "初评",
    size: 70,
    cell: ({ row }) => row.original.rating ?? "—",
  },
  {
    accessorKey: "calibrated_rating",
    header: "最终评级",
    size: 90,
    cell: ({ row }) =>
      row.original.calibrated_rating
        ? h(Badge, { variant: "success" }, () => row.original.calibrated_rating)
        : "—",
  },
  { accessorKey: "coefficient", header: "系数", size: 70 },
  {
    accessorKey: "status",
    header: "状态",
    size: 90,
    cell: ({ row }) =>
      h(
        Badge,
        {
          variant:
            PERF_REVIEW_STATUS_VARIANTS[row.original.status as PerfReviewStatus],
        },
        () => PERF_REVIEW_STATUS_LABELS[row.original.status as PerfReviewStatus],
      ),
  },
  {
    id: "actions",
    header: "操作",
    size: 160,
    cell: ({ row }) => {
      const item = row.original;
      const buttons = [] as ReturnType<typeof h>[];
      if (canWrite.value && item.cycle_status === "scoring" && item.status !== "calibrated") {
        buttons.push(
          h(
            Button,
            {
              variant: "ghost",
              size: "sm",
              "data-testid": `review-score-${item.id}`,
              onClick: () => openScore(item),
            },
            () => "评分",
          ),
        );
      }
      if (
        canCalibrate.value &&
        item.cycle_status === "calibrating" &&
        item.status === "submitted"
      ) {
        buttons.push(
          h(
            Button,
            {
              variant: "ghost",
              size: "sm",
              "data-testid": `review-calibrate-${item.id}`,
              onClick: () => openCalibrate(item),
            },
            () => "校准",
          ),
        );
      }
      if (!buttons.length) {
        buttons.push(h("span", { class: "text-muted-foreground text-xs" }, "—"));
      }
      return h("div", { class: "flex items-center gap-1" }, buttons);
    },
  },
] as ColumnDef<PerfReviewItem>[]);

const dataTable = useDataTable<PerfReviewItem>({
  columns: columns.value,
  remoteFetchFn: async ({ page, page_size }) => {
    const query: PerfReviewQuery = {
      page,
      page_size,
      cycle_id: cycleId.value === ALL ? undefined : cycleId.value,
      status: status.value === ALL ? undefined : status.value,
    };
    try {
      const res = await listPerfReviews(query);
      return envelope<PerfReviewItem>(res, page, page_size);
    } catch (error) {
      notifyError(error, getErrorMessage(error, "评估列表加载失败"));
      throw error;
    }
  },
});

function handleSearch() {
  dataTable.refresh(true);
}

function handleReset() {
  cycleId.value = ALL;
  status.value = ALL;
  dataTable.refresh(true);
}

/* ── 弹窗 ── */

const launchOpen = ref(false);
const scoreOpen = ref(false);
const scoreTarget = ref<PerfReviewItem | null>(null);
const calibrateOpen = ref(false);
const calibrateTarget = ref<PerfReviewItem | null>(null);

function openScore(item: PerfReviewItem) {
  scoreTarget.value = item;
  scoreOpen.value = true;
}

function openCalibrate(item: PerfReviewItem) {
  calibrateTarget.value = item;
  calibrateOpen.value = true;
}

function handleSaved(message: string) {
  notifySuccess(message);
  dataTable.refresh();
  if (cycleId.value !== ALL) {
    getPerfDistribution(cycleId.value)
      .then((res) => {
        distribution.value = res.data ?? null;
      })
      .catch(() => {});
  }
}

loadCycles();
</script>

<template>
  <AppPage
    title="评估管理"
    description="按周期批量发起评估、提交评分与评级校准；校准留痕后评级落定，收口时映射绩效系数供发薪消费"
  >
    <div class="flex min-h-0 flex-1 flex-col gap-4">
      <div
        v-if="distribution"
        class="ring-foreground/10 bg-card rounded-xl text-sm ring-1 shadow-sm px-5 py-4"
        data-testid="review-distribution"
      >
        <div class="mb-3 flex items-center gap-2 text-sm font-medium">
          评级分布（校准参考）
          <span class="text-muted-foreground text-xs font-normal">
            共 {{ distribution.total }} 人
            <template v-if="distribution.rules">
              · 规则线
              <template v-for="(limit, rating) in distribution.rules" :key="rating">
                {{ rating }}≤{{ limit }}%
              </template>
            </template>
          </span>
        </div>
        <div class="flex flex-col gap-1.5">
          <div
            v-for="rating in PERF_RATINGS"
            :key="rating"
            class="flex items-center gap-3"
          >
            <span class="text-muted-foreground w-4 text-xs">{{ rating }}</span>
            <div class="bg-muted h-4 flex-1 overflow-hidden rounded">
              <div
                class="bg-emerald-500 h-full rounded"
                :style="{
                  width: `${((distribution.ratings[rating]?.count ?? 0) / maxCount) * 100}%`,
                }"
              />
            </div>
            <span class="text-muted-foreground w-24 text-xs">
              {{ distribution.ratings[rating]?.count ?? 0 }} 人（{{ distribution.ratings[rating]?.percent ?? 0 }}%）
            </span>
          </div>
        </div>
      </div>

      <div class="ring-foreground/10 bg-card flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
        <div class="flex shrink-0 flex-wrap items-center gap-2 border-b px-5 py-3">
          <Select
            v-model="cycleId"
            trigger-class="w-48"
            :options="cycleOptions"
            data-testid="review-cycle-filter"
          />
          <Select
            v-model="status"
            trigger-class="w-32"
            :options="statusOptions"
            data-testid="review-status-filter"
          />
          <Button variant="outline" size="sm" data-testid="review-search" @click="handleSearch">搜索</Button>
          <Button variant="ghost" size="sm" data-testid="review-reset" @click="handleReset">重置</Button>
          <div class="flex-1" />
          <Button
            v-if="canWrite"
            size="sm"
            data-testid="review-launch"
            @click="launchOpen = true"
          >
            发起评估
          </Button>
        </div>
        <div class="flex min-h-0 flex-1 flex-col px-5 pt-4">
          <DataTable :data-table="dataTable" :fixed-layout="true" />
        </div>
      </div>
    </div>

    <ReviewLaunchModal v-model:open="launchOpen" @saved="handleSaved('评估已发起')" />
    <ReviewScoreModal v-model:open="scoreOpen" :review="scoreTarget" @saved="handleSaved('评分已提交')" />
    <ReviewCalibrateModal
      v-model:open="calibrateOpen"
      :review="calibrateTarget"
      @saved="handleSaved('校准已留痕')"
    />
  </AppPage>
</template>
