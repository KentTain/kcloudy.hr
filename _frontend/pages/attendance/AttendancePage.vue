<script setup lang="ts">
/**
 * 考勤管理页：筛选区（时间档位/部门/姓名）+ 考勤总览（统计卡+部门统计表，
 * 随筛选联动）+ 考勤记录列表（只读，Excel/AI 导入两条通道产生数据）。
 * 总览不设独立页面，直接置于列表上方。
 */
import type { ColumnDef } from "@tanstack/vue-table";
import { computed, h, onMounted, ref, watch } from "vue";

import {
  Badge,
  Button,
  DataTable,
  Input,
  OrganizationSelect,
  Select,
  useDataTable,
} from "@/components";
import AppPage from "@/framework/layouts/components/AppPage.vue";

import { getErrorMessage, notifyError } from "@/framework/utils/feedback";
import { useUserStore } from "@/framework/stores";

import { getAttendanceStats, listAttendanceRecords } from "@/hr/api/attendance";
import { getOrgTree } from "@/hr/api/reference";
import AttendanceAiImportModal from "@/hr/components/attendance/AttendanceAiImportModal.vue";
import AttendanceImportModal from "@/hr/components/attendance/AttendanceImportModal.vue";
import type { OrgTreeNode } from "@/hr/types/employee";
import {
  ATTENDANCE_SOURCE_LABELS,
  ATTENDANCE_STATUS_LABELS,
  ATTENDANCE_STATUS_VARIANTS,
  type AttendanceOrgStat,
  type AttendanceQuery,
  type AttendanceRecord,
  type AttendanceStats,
  TIME_RANGE_OPTIONS,
  type TimeRangeValue,
  formatCheckTime,
  timeRangeToDates,
} from "@/hr/types/attendance";

const userStore = useUserStore();
const canImport = computed(() => userStore.hasPermission("hr:attendance:import"));

/* ── 筛选区 ── */

const timeRange = ref<TimeRangeValue>("1m");
const orgIds = ref<string[]>([]);
const keyword = ref("");

const timeRangeOptions = TIME_RANGE_OPTIONS.map((option) => ({
  value: option.value,
  label: option.label,
}));

/* ── 考勤总览 ── */

const stats = ref<AttendanceStats | null>(null);
const statsLoading = ref(false);
const orgTree = ref<OrgTreeNode[]>([]);

function findOrgNode(nodes: OrgTreeNode[], id: string): OrgTreeNode | null {
  for (const node of nodes) {
    if (node.id === id) return node;
    const child = findOrgNode(node.children ?? [], id);
    if (child) return child;
  }
  return null;
}

function orgNameOf(orgId: string | null): string {
  if (!orgId) return "--";
  return findOrgNode(orgTree.value, orgId)?.name ?? orgId;
}

const statCards = computed(() => {
  const cards = stats.value?.cards;
  return [
    { key: "attendance", label: "出勤人次", value: cards?.attendance_count ?? 0 },
    { key: "late", label: "迟到人次", value: cards?.late_count ?? 0 },
    { key: "early-leave", label: "早退人次", value: cards?.early_leave_count ?? 0 },
    { key: "absent", label: "缺勤人次", value: cards?.absent_count ?? 0 },
    {
      key: "rate",
      label: "出勤率",
      value: cards?.attendance_rate == null ? "—" : `${cards.attendance_rate.toFixed(2)}%`,
    },
  ];
});

function rateText(rate: number | null): string {
  return rate == null ? "—" : `${rate.toFixed(2)}%`;
}

async function loadStats() {
  statsLoading.value = true;
  const range = timeRangeToDates(timeRange.value);
  try {
    const res = await getAttendanceStats({
      date_from: range.date_from,
      date_to: range.date_to,
      org_id: orgIds.value[0] || undefined,
      keyword: keyword.value || undefined,
    });
    stats.value = res.data ?? null;
  } catch (error) {
    notifyError(error, getErrorMessage(error, "考勤总览加载失败"));
    stats.value = null;
  } finally {
    statsLoading.value = false;
  }
}

/* ── 考勤记录列表 ── */

const columns = ref<ColumnDef<AttendanceRecord>[]>([
  { accessorKey: "employee_no", header: "工号", size: 100 },
  { accessorKey: "employee_name", header: "姓名", size: 100 },
  { id: "org", header: "部门", size: 120, cell: ({ row }) => orgNameOf(row.original.org_id) },
  { accessorKey: "work_date", header: "日期", size: 110 },
  {
    id: "check_in",
    header: "上班打卡",
    size: 90,
    cell: ({ row }) => formatCheckTime(row.original.check_in_time),
  },
  {
    id: "check_out",
    header: "下班打卡",
    size: 90,
    cell: ({ row }) => formatCheckTime(row.original.check_out_time),
  },
  {
    accessorKey: "work_hours",
    header: "工作时长（小时）",
    size: 130,
    cell: ({ row }) => row.original.work_hours ?? "--",
  },
  {
    accessorKey: "overtime_hours",
    header: "加班时长（小时）",
    size: 130,
    cell: ({ row }) => row.original.overtime_hours ?? "--",
  },
  {
    accessorKey: "status",
    header: "状态",
    size: 110,
    cell: ({ row }) =>
      h(Badge, { variant: ATTENDANCE_STATUS_VARIANTS[row.original.status] ?? "secondary" }, () =>
        ATTENDANCE_STATUS_LABELS[row.original.status] ?? row.original.status,
      ),
  },
  {
    accessorKey: "source",
    header: "数据来源",
    size: 100,
    cell: ({ row }) => ATTENDANCE_SOURCE_LABELS[row.original.source] ?? row.original.source,
  },
  {
    accessorKey: "remark",
    header: "备注",
    cell: ({ row }) => row.original.remark || "--",
  },
] as ColumnDef<AttendanceRecord>[]);

const dataTable = useDataTable<AttendanceRecord>({
  columns: columns.value,
  remoteFetchFn: async ({ page, page_size }) => {
    const range = timeRangeToDates(timeRange.value);
    const query: AttendanceQuery = {
      page,
      page_size,
      date_from: range.date_from,
      date_to: range.date_to,
      org_id: orgIds.value[0] || undefined,
      keyword: keyword.value || undefined,
    };
    const res = await listAttendanceRecords(query);
    const rows = res.data ?? [];
    return {
      code: res.code,
      data: rows,
      msg: res.msg,
      page: res.page || page,
      page_size: res.page_size || page_size,
      total: res.total || 0,
    };
  },
});

function handleSearch() {
  dataTable.refresh(true);
  void loadStats();
}

function handleReset() {
  timeRange.value = "1m";
  orgIds.value = [];
  keyword.value = "";
  dataTable.refresh(true);
  void loadStats();
}

/** 时间档位变更即时联动总览与列表 */
watch(timeRange, () => {
  dataTable.refresh(true);
  void loadStats();
});

/* ── 导入弹窗 ── */

const excelImportOpen = ref(false);
const aiImportOpen = ref(false);

function refreshAll() {
  dataTable.refresh();
  void loadStats();
}

onMounted(() => {
  void loadStats();
  void getOrgTree()
    .then((res) => {
      orgTree.value = res.data ?? [];
    })
    .catch(() => {
      orgTree.value = [];
    });
});

const orgStats = computed<AttendanceOrgStat[]>(() => stats.value?.org_slices ?? []);
</script>

<template>
  <AppPage
    title="考勤管理"
    description="考勤记录统一入口：Excel 与 AI 两条导入通道产生数据，总览随筛选联动展示"
  >
    <div class="flex h-full min-h-0 flex-col gap-4">
      <!-- 筛选区 -->
      <div class="bg-card ring-foreground/10 flex shrink-0 flex-wrap items-center gap-2 rounded-xl px-5 py-3 text-sm ring-1 shadow-sm">
        <Select
          v-model="timeRange"
          trigger-class="w-32"
          :options="timeRangeOptions"
          data-testid="attendance-time-filter"
        />
        <OrganizationSelect
          v-model="orgIds"
          :multiple="false"
          placeholder="部门"
          class="w-44"
          data-testid="attendance-org-filter"
        />
        <Input
          v-model="keyword"
          class="w-44"
          placeholder="姓名/工号"
          data-testid="attendance-keyword-input"
          @keyup.enter="handleSearch"
        />
        <Button variant="outline" size="sm" data-testid="attendance-search" @click="handleSearch">搜索</Button>
        <Button variant="ghost" size="sm" data-testid="attendance-filter-reset" @click="handleReset">重置</Button>
      </div>

      <!-- 考勤总览区 -->
      <div class="flex shrink-0 flex-col gap-3" data-testid="attendance-overview">
        <div class="grid shrink-0 grid-cols-2 gap-4 md:grid-cols-5" data-testid="attendance-stat-cards">
          <div
            v-for="card in statCards"
            :key="card.key"
            class="bg-card ring-foreground/10 rounded-xl p-4 text-sm ring-1 shadow-sm"
            :data-testid="`stat-card-${card.key}`"
          >
            <p class="text-muted-foreground text-xs">{{ card.label }}</p>
            <p class="mt-1 text-2xl font-semibold">{{ card.value }}</p>
          </div>
        </div>

        <!-- 部门统计表 -->
        <div class="bg-card ring-foreground/10 shrink-0 overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
          <div class="border-b px-5 py-3 text-xs font-medium">部门统计</div>
          <div class="max-h-56 overflow-auto px-5 py-2">
            <table class="w-full text-left text-xs" data-testid="attendance-org-stats">
              <thead class="text-muted-foreground border-b">
                <tr>
                  <th class="py-2 pr-3 font-medium">部门</th>
                  <th class="py-2 pr-3 font-medium">记录数</th>
                  <th class="py-2 pr-3 font-medium">出勤人次</th>
                  <th class="py-2 pr-3 font-medium">迟到</th>
                  <th class="py-2 pr-3 font-medium">早退</th>
                  <th class="py-2 pr-3 font-medium">缺卡</th>
                  <th class="py-2 pr-3 font-medium">缺勤</th>
                  <th class="py-2 font-medium">出勤率</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in orgStats" :key="row.org_id" class="border-b last:border-0">
                  <td class="py-2 pr-3 font-medium">{{ orgNameOf(row.org_id) }}</td>
                  <td class="py-2 pr-3">{{ row.total_records }}</td>
                  <td class="py-2 pr-3">{{ row.attendance_count }}</td>
                  <td class="py-2 pr-3">{{ row.late_count }}</td>
                  <td class="py-2 pr-3">{{ row.early_leave_count }}</td>
                  <td class="py-2 pr-3">{{ row.missing_card_count }}</td>
                  <td class="py-2 pr-3">{{ row.absent_count }}</td>
                  <td class="py-2">{{ rateText(row.attendance_rate) }}</td>
                </tr>
                <tr v-if="!orgStats.length && !statsLoading">
                  <td colspan="8" class="text-muted-foreground py-4 text-center">暂无考勤数据</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- 考勤记录列表区 -->
      <div class="ring-foreground/10 bg-card flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
        <div class="flex shrink-0 items-center justify-between gap-2 border-b px-5 py-3">
          <div class="text-xs font-medium">考勤记录</div>
          <div v-if="canImport" class="flex items-center gap-2">
            <Button variant="outline" size="sm" data-testid="open-excel-import" @click="excelImportOpen = true">
              Excel 导入
            </Button>
            <Button size="sm" data-testid="open-ai-import" @click="aiImportOpen = true">AI 导入</Button>
          </div>
        </div>
        <div class="flex min-h-0 flex-1 flex-col px-5 pt-4">
          <DataTable :data-table="dataTable" :fixed-layout="true" />
        </div>
      </div>
    </div>

    <AttendanceImportModal v-model:open="excelImportOpen" @saved="refreshAll" />
    <AttendanceAiImportModal v-model:open="aiImportOpen" @saved="refreshAll" />
  </AppPage>
</template>
