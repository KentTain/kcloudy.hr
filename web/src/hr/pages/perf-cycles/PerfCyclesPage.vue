<script setup lang="ts">
/**
 * 考核周期页：绩效管理顶层容器。周期列表（状态机操作/概览）+ 新建/编辑（仅 draft）+
 * 目标整批提交弹窗。状态机单向推进 draft→active→scoring→calibrating→closed，
 * 每次推进二次确认；收口后只读（评级系数供发薪消费）。
 * 评估发起/评分/校准见评估管理页（批 C）。
 */
import type { ColumnDef } from "@tanstack/vue-table";
import { computed, h, ref } from "vue";

import {
  Badge,
  Button,
  DataTable,
  DateInput,
  Select,
  useDataTable,
} from "@/components";
import AppPage from "@/framework/layouts/components/AppPage.vue";

import { useUserStore } from "@/framework/stores";
import {
  confirmAction,
  getErrorMessage,
  notifyError,
  notifySuccess,
} from "@/framework/utils/feedback";

import { deletePerfCycle, listPerfCycles, transitionPerfCycle } from "@/hr/api/perf";
import CycleFormModal from "@/hr/components/perf/CycleFormModal.vue";
import CycleOverviewDrawer from "@/hr/components/perf/CycleOverviewDrawer.vue";
import GoalSubmitModal from "@/hr/components/perf/GoalSubmitModal.vue";
import {
  PERF_CYCLE_STATUS_LABELS,
  PERF_CYCLE_STATUS_VARIANTS,
  PERF_TRANSITION_LABELS,
  PERF_TRANSITIONS,
  type PerfCycleItem,
  type PerfCycleQuery,
  type PerfCycleStatus,
} from "@/hr/types/perf";

const userStore = useUserStore();
const canWrite = computed(() => userStore.hasPermission("hr:perf_cycle:write"));
const canDelete = computed(() => userStore.hasPermission("hr:perf_cycle:delete"));

const ALL = "__all__";

const status = ref<PerfCycleStatus | typeof ALL>(ALL);
const dateFrom = ref("");
const dateTo = ref("");

const statusOptions = [
  { value: ALL, label: "全部状态" },
  ...(Object.keys(PERF_CYCLE_STATUS_LABELS) as PerfCycleStatus[]).map((value) => ({
    value,
    label: PERF_CYCLE_STATUS_LABELS[value],
  })),
];

/** 信封适配：data 裸数组 + 顶层 total */
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

const columns = ref<ColumnDef<PerfCycleItem>[]>([
  { accessorKey: "name", header: "周期名", size: 160 },
  {
    accessorKey: "status",
    header: "状态",
    size: 100,
    cell: ({ row }) =>
      h(
        Badge,
        { variant: PERF_CYCLE_STATUS_VARIANTS[row.original.status as PerfCycleStatus] },
        () => PERF_CYCLE_STATUS_LABELS[row.original.status as PerfCycleStatus],
      ),
  },
  {
    id: "date_range",
    header: "起止日期",
    size: 200,
    cell: ({ row }) => `${row.original.start_date} ~ ${row.original.end_date}`,
  },
  { accessorKey: "goal_count", header: "目标数", size: 90 },
  { accessorKey: "review_count", header: "评估数", size: 90 },
  {
    id: "actions",
    header: "操作",
    size: 240,
    cell: ({ row }) => {
      const item = row.original;
      const buttons = [] as ReturnType<typeof h>[];
      buttons.push(
        h(
          Button,
          {
            variant: "ghost",
            size: "sm",
            "data-testid": `cycle-overview-${item.id}`,
            onClick: () => openOverview(item),
          },
          () => "概览",
        ),
      );
      if (canWrite.value) {
        const nextAction = PERF_TRANSITIONS[item.status as PerfCycleStatus][0];
        if (nextAction) {
          buttons.push(
            h(
              Button,
              {
                variant: "ghost",
                size: "sm",
                "data-testid": `cycle-transition-${nextAction}-${item.id}`,
                onClick: () => handleTransition(item, nextAction),
              },
              () => PERF_TRANSITION_LABELS[nextAction],
            ),
          );
        }
        if (item.status === "draft") {
          buttons.push(
            h(
              Button,
              {
                variant: "ghost",
                size: "sm",
                "data-testid": `cycle-edit-${item.id}`,
                onClick: () => openForm(item),
              },
              () => "编辑",
            ),
          );
        }
      }
      if (canDelete.value && item.status === "draft") {
        buttons.push(
          h(
            Button,
            {
              variant: "ghost",
              size: "sm",
              "data-testid": `cycle-delete-${item.id}`,
              onClick: () => handleDelete(item),
            },
            () => "删除",
          ),
        );
      }
      return h("div", { class: "flex items-center gap-1" }, buttons);
    },
  },
] as ColumnDef<PerfCycleItem>[]);

const dataTable = useDataTable<PerfCycleItem>({
  columns: columns.value,
  remoteFetchFn: async ({ page, page_size }) => {
    const query: PerfCycleQuery = {
      page,
      page_size,
      status: status.value === ALL ? undefined : status.value,
      date_from: dateFrom.value || undefined,
      date_to: dateTo.value || undefined,
    };
    try {
      const res = await listPerfCycles(query);
      return envelope<PerfCycleItem>(res, page, page_size);
    } catch (error) {
      notifyError(error, getErrorMessage(error, "考核周期加载失败"));
      throw error;
    }
  },
});

function handleSearch() {
  dataTable.refresh(true);
}

function handleReset() {
  status.value = ALL;
  dateFrom.value = "";
  dateTo.value = "";
  dataTable.refresh(true);
}

/* ── 状态机推进（二次确认）── */

async function handleTransition(item: PerfCycleItem, action: string) {
  const label = PERF_TRANSITION_LABELS[action];
  const confirmed = await confirmAction(
    `确认将周期「${item.name}」${label}？状态推进后不可回退`,
  );
  if (!confirmed) return;
  try {
    await transitionPerfCycle(item.id, action as "activate");
    notifySuccess(`周期已${label}`);
    dataTable.refresh();
  } catch (error) {
    notifyError(error, getErrorMessage(error, `周期${label}失败`));
  }
}

async function handleDelete(item: PerfCycleItem) {
  const confirmed = await confirmAction(`确认删除周期「${item.name}」？仅草稿可删除`);
  if (!confirmed) return;
  try {
    await deletePerfCycle(item.id);
    notifySuccess("周期已删除");
    dataTable.refresh();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "周期删除失败"));
  }
}

/* ── 新建/编辑弹窗 ── */

const formOpen = ref(false);
const formTarget = ref<PerfCycleItem | null>(null);

function openForm(item: PerfCycleItem | null) {
  formTarget.value = item;
  formOpen.value = true;
}

/* ── 概览抽屉 ── */

const overviewOpen = ref(false);
const overviewTarget = ref<PerfCycleItem | null>(null);

function openOverview(item: PerfCycleItem) {
  overviewTarget.value = item;
  overviewOpen.value = true;
}

function overviewTransition(action: string) {
  if (!overviewTarget.value) return;
  overviewOpen.value = false;
  handleTransition(overviewTarget.value, action);
}

/* ── 目标整批提交 ── */

const goalOpen = ref(false);

function openGoalSubmit() {
  goalOpen.value = true;
}
</script>

<template>
  <AppPage
    title="考核周期"
    description="按周期组织目标制定、评估打分与评级校准，状态机驱动各阶段开放范围；评级落定后供发薪试算消费绩效系数"
  >
    <div class="ring-foreground/10 bg-card flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
      <div class="flex shrink-0 flex-wrap items-center gap-2 border-b px-5 py-3">
        <Select
          v-model="status"
          trigger-class="w-32"
          :options="statusOptions"
          data-testid="cycle-status-filter"
        />
        <DateInput
          v-model="dateFrom"
          placeholder="起始日期"
          data-testid="cycle-date-from"
        />
        <DateInput
          v-model="dateTo"
          placeholder="截止日期"
          data-testid="cycle-date-to"
        />
        <Button variant="outline" size="sm" data-testid="cycle-search" @click="handleSearch">搜索</Button>
        <Button variant="ghost" size="sm" data-testid="cycle-reset" @click="handleReset">重置</Button>
        <div class="flex-1" />
        <Button
          v-if="canWrite"
          size="sm"
          data-testid="cycle-create"
          @click="openForm(null)"
        >
          新建周期
        </Button>
        <Button
          v-if="canWrite"
          variant="outline"
          size="sm"
          data-testid="cycle-goal-submit"
          @click="openGoalSubmit"
        >
          制定目标
        </Button>
      </div>
      <div class="flex min-h-0 flex-1 flex-col px-5 pt-4">
        <DataTable :data-table="dataTable" :fixed-layout="true" />
      </div>
    </div>

    <CycleFormModal v-model:open="formOpen" :cycle="formTarget" @saved="dataTable.refresh()" />
    <CycleOverviewDrawer
      v-model:open="overviewOpen"
      :cycle="overviewTarget"
      @transition="overviewTransition"
    />
    <GoalSubmitModal v-model:open="goalOpen" @saved="dataTable.refresh()" />
  </AppPage>
</template>
