<script setup lang="ts">
/**
 * 招聘需求页：需求列表检索（状态/优先级/部门/关键词）+ 三步创建弹窗
 * + 渠道发布弹窗 + 详情侧滑（信息卡/渠道发布/三段漏斗/候选人流转）。
 */
import type { ColumnDef } from "@tanstack/vue-table";
import { computed, h, onMounted, ref } from "vue";

import {
  Badge,
  Button,
  DataTable,
  Input,
  Select,
  useDataTable,
} from "@/components";
import { OrganizationSelect } from "@/components";
import AppPage from "@/framework/layouts/components/AppPage.vue";

import { getErrorMessage, notifyError, notifySuccess, confirmAction } from "@/framework/utils/feedback";
import { useUserStore } from "@/framework/stores";

import { closeRequisition, listRequisitions } from "@/hr/api/recruiting";
import { getOrgTree, getPositionOptions } from "@/hr/api/reference";
import RequisitionDetailSheet from "@/hr/components/recruiting/RequisitionDetailSheet.vue";
import RequisitionFormModal from "@/hr/components/recruiting/RequisitionFormModal.vue";
import RequisitionPublishModal from "@/hr/components/recruiting/RequisitionPublishModal.vue";
import RequisitionRowActions from "@/hr/components/recruiting/RequisitionRowActions.vue";
import type { OrgTreeNode } from "@/hr/types/employee";
import {
  REQUISITION_PRIORITY_LABELS,
  REQUISITION_PRIORITY_OPTIONS,
  REQUISITION_PRIORITY_VARIANTS,
  REQUISITION_STATUS_LABELS,
  REQUISITION_STATUS_VARIANTS,
  type Requisition,
  type RequisitionPriority,
  type RequisitionStatus,
} from "@/hr/types/recruiting";

const userStore = useUserStore();
const canWrite = computed(() => userStore.hasPermission("hr:requisition:write"));
const canReadCandidates = computed(() => userStore.hasPermission("hr:candidate:read"));

/* ── 参照解析（组织/岗位 ID → 名称） ── */

const orgTree = ref<OrgTreeNode[]>([]);
const positionOptions = ref<{ id: string; name: string }[]>([]);

async function loadReferences() {
  try {
    const res = await getOrgTree();
    orgTree.value = res.data ?? [];
  } catch {
    orgTree.value = [];
  }
  try {
    const res = await getPositionOptions();
    positionOptions.value = (res.data ?? []).map((p) => ({ id: p.id, name: p.name }));
  } catch {
    positionOptions.value = [];
  }
}

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

function positionNameOf(positionId: string | null): string {
  if (!positionId) return "--";
  return positionOptions.value.find((p) => p.id === positionId)?.name ?? positionId;
}

/* ── 筛选 ── */

const statusFilter = ref("all");
const priorityFilter = ref("all");
const orgIds = ref<string[]>([]);
const keyword = ref("");

const statusOptions = [
  { value: "all", label: "全部状态" },
  ...(Object.keys(REQUISITION_STATUS_LABELS) as RequisitionStatus[]).map((value) => ({
    value,
    label: REQUISITION_STATUS_LABELS[value],
  })),
];

const priorityOptions = [
  { value: "all", label: "全部优先级" },
  ...REQUISITION_PRIORITY_OPTIONS,
];

function handleResetFilters() {
  statusFilter.value = "all";
  priorityFilter.value = "all";
  orgIds.value = [];
  keyword.value = "";
  dataTable.refresh(true);
}

/* ── 列表 ── */

function salaryRangeOf(item: Requisition): string {
  if (item.salary_min === null && item.salary_max === null) return "--";
  return `${item.salary_min ?? ""} ~ ${item.salary_max ?? ""}`;
}

const columns = computed<ColumnDef<Requisition>[]>(() => [
  { accessorKey: "req_no", header: "需求编号", size: 140 },
  { accessorKey: "title", header: "职位名称", size: 180 },
  {
    accessorKey: "org_id",
    header: "部门",
    size: 120,
    cell: ({ row }) => orgNameOf(row.original.org_id),
  },
  {
    id: "headcount",
    header: "入职/招聘",
    size: 90,
    cell: ({ row }) => `${row.original.filled_count} / ${row.original.headcount}`,
  },
  {
    accessorKey: "job_level",
    header: "职级",
    size: 80,
    cell: ({ row }) => row.original.job_level ?? "--",
  },
  {
    id: "salary",
    header: "薪酬区间",
    size: 130,
    cell: ({ row }) => h("span", { class: "text-muted-foreground" }, salaryRangeOf(row.original)),
  },
  {
    accessorKey: "priority",
    header: "优先级",
    size: 90,
    cell: ({ row }) =>
      h(Badge, { variant: REQUISITION_PRIORITY_VARIANTS[row.original.priority] }, () =>
        REQUISITION_PRIORITY_LABELS[row.original.priority] ?? row.original.priority,
      ),
  },
  {
    accessorKey: "status",
    header: "状态",
    size: 90,
    cell: ({ row }) =>
      h(Badge, { variant: REQUISITION_STATUS_VARIANTS[row.original.status] }, () =>
        REQUISITION_STATUS_LABELS[row.original.status] ?? row.original.status,
      ),
  },
  {
    id: "channels",
    header: "已发布渠道",
    size: 100,
    cell: ({ row }) =>
      h("span", { class: "text-muted-foreground" }, `${row.original.postings?.length ?? 0} 个渠道`),
  },
  {
    id: "actions",
    header: "操作",
    size: 90,
    cell: ({ row }) =>
      h(RequisitionRowActions, {
        requisition: row.original,
        canWrite: canWrite.value,
        onDetail: (item: Requisition) => openDetail(item),
        onPublish: (item: Requisition) => openPublish(item),
        onClose: (item: Requisition) => void handleClose(item),
      }),
  },
] as ColumnDef<Requisition>[]);

const dataTable = useDataTable<Requisition>({
  columns: columns.value,
  remoteFetchFn: async ({ page, page_size }) => {
    const res = await listRequisitions({
      page,
      page_size,
      status: statusFilter.value === "all" ? undefined : (statusFilter.value as RequisitionStatus),
      priority: priorityFilter.value === "all" ? undefined : (priorityFilter.value as RequisitionPriority),
      org_id: orgIds.value[0] || undefined,
      keyword: keyword.value || undefined,
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

/* ── 创建 / 发布 / 关闭 / 详情 ── */

const formOpen = ref(false);

const publishOpen = ref(false);
const publishTarget = ref<Requisition | null>(null);

const detailOpen = ref(false);
const detailRequisitionId = ref<string | null>(null);

function openDetail(item: Requisition) {
  detailRequisitionId.value = item.id;
  detailOpen.value = true;
}

function openPublish(item: Requisition) {
  publishTarget.value = item;
  publishOpen.value = true;
}

async function handleClose(item: Requisition) {
  if (!(await confirmAction(`确定关闭需求「${item.title}」？关闭后不可再接受投递与流转。`))) return;
  try {
    await closeRequisition(item.id);
    notifySuccess("需求已关闭");
    dataTable.refresh();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "关闭需求失败"));
  }
}

onMounted(() => {
  void loadReferences();
});
</script>

<template>
  <AppPage title="招聘需求" description="招聘需求管理：分步创建、渠道发布与漏斗进展跟踪">
    <template #actions>
      <Button v-if="canWrite" data-testid="open-requisition-form" @click="formOpen = true">新建需求</Button>
    </template>

    <div class="bg-card ring-foreground/10 flex h-full min-h-0 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
      <!-- 筛选栏 -->
      <div class="flex shrink-0 flex-wrap items-center gap-2 border-b px-5 py-3">
        <Select v-model="statusFilter" trigger-class="w-32" :options="statusOptions" data-testid="requisition-status-filter" />
        <Select v-model="priorityFilter" trigger-class="w-32" :options="priorityOptions" data-testid="requisition-priority-filter" />
        <OrganizationSelect v-model="orgIds" :multiple="false" placeholder="按部门" class="w-44" data-testid="requisition-org-filter" />
        <Input
          v-model="keyword"
          class="w-44"
          placeholder="职位名称/需求编号"
          data-testid="requisition-keyword-input"
          @keyup.enter="dataTable.refresh(true)"
        />
        <Button variant="outline" size="sm" data-testid="requisition-search" @click="dataTable.refresh(true)">搜索</Button>
        <Button variant="ghost" size="sm" data-testid="requisition-filter-reset" @click="handleResetFilters">重置</Button>
      </div>

      <!-- 表格区 -->
      <div class="flex min-h-0 flex-1 flex-col px-5 pt-4">
        <DataTable :data-table="dataTable" :fixed-layout="true" />
      </div>
    </div>

    <!-- 三步创建弹窗 -->
    <RequisitionFormModal v-model:open="formOpen" @saved="dataTable.refresh()" />

    <!-- 渠道发布弹窗 -->
    <RequisitionPublishModal
      v-model:open="publishOpen"
      :requisition="publishTarget"
      @published="dataTable.refresh()"
    />

    <!-- 需求详情侧滑 -->
    <RequisitionDetailSheet
      v-model:open="detailOpen"
      :requisition-id="detailRequisitionId"
      :can-write="canWrite"
      :can-read-candidates="canReadCandidates"
      :org-name-of="orgNameOf"
      :position-name-of="positionNameOf"
      @refresh="dataTable.refresh()"
      @publish="openPublish"
    />
  </AppPage>
</template>
