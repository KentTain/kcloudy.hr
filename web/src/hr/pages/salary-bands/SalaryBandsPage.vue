<script setup lang="ts">
/**
 * 职级薪带页：带宽对照表（min/mid/max + 行内带宽条带可视化）+ 版本管理。
 * 版本语义：effective_to 空 = 当前生效；历史版本只读；未生效版本可编辑删除。
 */
import type { ColumnDef } from "@tanstack/vue-table";
import { computed, h, ref } from "vue";

import { Badge, Button, DataTable, Input, Select, useDataTable } from "@/components";
import AppPage from "@/framework/layouts/components/AppPage.vue";

import { confirmAction, getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";
import { useUserStore } from "@/framework/stores";

import { deleteSalaryBand, listSalaryBands } from "@/hr/api/salary";
import BandFormModal from "@/hr/components/salary/BandFormModal.vue";
import {
  BAND_EFFECTIVE_STATUS_LABELS,
  BAND_EFFECTIVE_STATUS_VARIANTS,
  bandEffectiveStatus,
  type BandEffectiveStatus,
  type SalaryBand,
} from "@/hr/types/salary";

const userStore = useUserStore();
const canWrite = computed(() => userStore.hasPermission("hr:salary_band:write"));

/* ── 筛选 ── */

const jobLevelFilter = ref("");
const statusFilter = ref("all");

const statusSelectOptions = computed(() => [
  { value: "all", label: "全部状态" },
  ...(Object.entries(BAND_EFFECTIVE_STATUS_LABELS) as [BandEffectiveStatus, string][]).map(
    ([value, label]) => ({ value, label }),
  ),
]);

function handleResetFilters() {
  jobLevelFilter.value = "";
  statusFilter.value = "all";
  dataTable.refresh(true);
}

/* ── 带宽条带 ── */

/** 行内相对位置：mid 点位 = (mid-min)/(max-min)；异常数据（max≤min）退化为居中标记 */
function midPercentOf(band: SalaryBand): number {
  const span = band.max_salary - band.min_salary;
  if (span <= 0) return 50;
  const pct = ((band.mid_salary - band.min_salary) / span) * 100;
  return Math.min(100, Math.max(0, pct));
}

const money = (value: number) => value.toLocaleString("zh-CN", { minimumFractionDigits: 2 });

/* ── 列表 ── */

const columns = computed<ColumnDef<SalaryBand>[]>(() => [
  { accessorKey: "job_level", header: "职级", size: 90 },
  {
    accessorKey: "min_salary",
    header: "带宽下限",
    size: 110,
    cell: ({ row }) => money(row.original.min_salary),
  },
  {
    accessorKey: "mid_salary",
    header: "中位值",
    size: 110,
    cell: ({ row }) => money(row.original.mid_salary),
  },
  {
    accessorKey: "max_salary",
    header: "带宽上限",
    size: 110,
    cell: ({ row }) => money(row.original.max_salary),
  },
  {
    id: "band_visual",
    header: "带宽条带",
    size: 180,
    cell: ({ row }) => {
      const band = row.original;
      return h("div", { class: "relative h-2 w-full max-w-40 rounded-full bg-muted", title: `${band.min_salary} — ${band.mid_salary} — ${band.max_salary}` }, [
        h("span", {
          class: "absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary ring-2 ring-background",
          style: { left: `${midPercentOf(band)}%` },
        }),
      ]);
    },
  },
  {
    accessorKey: "effective_from",
    header: "生效起",
    size: 110,
  },
  {
    id: "effective_to",
    header: "生效止",
    size: 190,
    cell: ({ row }) => {
      const band = row.original;
      const status = bandEffectiveStatus(band);
      return h("div", { class: "flex items-center gap-2" }, [
        h("span", {}, band.effective_to ?? "--"),
        h(Badge, { variant: BAND_EFFECTIVE_STATUS_VARIANTS[status] }, () => BAND_EFFECTIVE_STATUS_LABELS[status]),
      ]);
    },
  },
  {
    id: "actions",
    header: "操作",
    size: 150,
    cell: ({ row }) => {
      const band = row.original;
      const status = bandEffectiveStatus(band);
      const buttons = [];
      if (!canWrite.value) return h("span", { class: "text-muted-foreground" }, "--");
      if (status === "active") {
        // 当前版本只读，入口是新建版本（预填带宽，后端自动闭合旧区间）
        buttons.push(
          h(Button, { variant: "ghost", size: "sm", onClick: () => openFormModal(band) }, () => "新建版本"),
        );
      } else if (status === "upcoming") {
        buttons.push(
          h(Button, { variant: "ghost", size: "sm", onClick: () => openFormModal(band) }, () => "编辑"),
        );
        buttons.push(
          h(Button, { variant: "ghost", size: "sm", onClick: () => removeBand(band) }, () => "删除"),
        );
      } else {
        return h("span", { class: "text-muted-foreground" }, "只读");
      }
      return h("div", { class: "flex items-center gap-1" }, buttons);
    },
  },
] as ColumnDef<SalaryBand>[]);

const dataTable = useDataTable<SalaryBand>({
  columns: columns.value,
  remoteFetchFn: async ({ page, page_size }) => {
    const res = await listSalaryBands({
      page,
      page_size,
      job_level: jobLevelFilter.value || undefined,
      effective_status:
        statusFilter.value === "all" ? undefined : (statusFilter.value as BandEffectiveStatus),
    });
    return {
      code: res.code,
      data: res.data ?? [],
      msg: res.msg,
      page: res.page || page,
      page_size: res.page_size || page_size,
      total: res.total || 0,
    };
  },
});

/* ── 表单弹窗 ── */

const formModalOpen = ref(false);
const formBand = ref<SalaryBand | null>(null);

function openFormModal(band: SalaryBand | null = null) {
  formBand.value = band;
  formModalOpen.value = true;
}

function handleSaved() {
  dataTable.refresh();
}

async function removeBand(band: SalaryBand) {
  if (
    !(await confirmAction(
      `确定删除职级「${band.job_level}」的未生效薪带版本？该操作不可恢复。`,
    ))
  ) {
    return;
  }
  try {
    await deleteSalaryBand(band.id);
    notifySuccess("薪带版本已删除");
    dataTable.refresh();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "删除失败：仅未生效版本可删除"));
  }
}
</script>

<template>
  <AppPage title="职级薪带" description="按职级定义薪酬带宽（min/mid/max），作为定薪与调薪的对标基准">
    <template #actions>
      <Button v-if="canWrite" data-testid="open-create-band" @click="openFormModal(null)">
        新建薪带
      </Button>
    </template>

    <div class="bg-card ring-foreground/10 flex h-full min-h-0 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
      <!-- 筛选栏 -->
      <div class="flex shrink-0 flex-wrap items-center gap-2 border-b px-5 py-3">
        <Input
          v-model="jobLevelFilter"
          class="w-32"
          placeholder="职级"
          data-testid="band-job-level-filter"
          @keyup.enter="dataTable.refresh(true)"
        />
        <Select
          v-model="statusFilter"
          trigger-class="w-32"
          :options="statusSelectOptions"
          data-testid="band-status-filter"
        />
        <Button variant="outline" size="sm" data-testid="band-search" @click="dataTable.refresh(true)">搜索</Button>
        <Button variant="ghost" size="sm" data-testid="band-filter-reset" @click="handleResetFilters">重置</Button>
      </div>

      <!-- 表格区 -->
      <div class="flex min-h-0 flex-1 flex-col px-5 pt-4">
        <DataTable :data-table="dataTable" :fixed-layout="true" />
      </div>
    </div>

    <BandFormModal v-model:open="formModalOpen" :band="formBand" @saved="handleSaved" />
  </AppPage>
</template>
