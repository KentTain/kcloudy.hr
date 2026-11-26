<script setup lang="ts">
/**
 * 招聘聚合测试页（流程测试载体）：聚合单列表检索 + 新建/详情/编辑侧滑，
 * 展示父（需求字段）- 子（申请明细）- 孙（行内 Offer）三级结构。
 */
import type { ColumnDef } from "@tanstack/vue-table";
import { computed, h, onMounted, ref } from "vue";
import { Plus, RefreshCw } from "@lucide/vue";
import {
  Badge,
  Button,
  DataTable,
  Input,
  OrganizationSelect,
  RowActions,
  Select,
  useDataTable,
} from "@/components";
import AppPage from "@/framework/layouts/components/AppPage.vue";
import { useUserStore } from "@/framework/stores";

import { getOrgTree } from "@/hr/api/reference";
import { listRequisitionBundles } from "@/hr/api/requisitionBundle";
import RequisitionBundleSheet from "@/hr/components/recruiting/RequisitionBundleSheet.vue";
import type { OrgTreeNode } from "@/hr/types/employee";
import {
  REQUISITION_PRIORITY_LABELS,
  REQUISITION_PRIORITY_VARIANTS,
  REQUISITION_STATUS_LABELS,
  REQUISITION_STATUS_VARIANTS,
  type RequisitionBundleListItem,
  type RequisitionStatus,
} from "@/hr/types/recruiting";

const userStore = useUserStore();
const canWrite = computed(() => userStore.hasPermission("hr:requisition:write"));

/* ── 参照解析（组织 ID → 名称） ── */

const orgTree = ref<OrgTreeNode[]>([]);

async function loadReferences() {
  try {
    const res = await getOrgTree();
    orgTree.value = res.data ?? [];
  } catch {
    orgTree.value = [];
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

/* ── 筛选 ── */

const statusFilter = ref("all");
const keyword = ref("");

const statusOptions = [
  { value: "all", label: "全部状态" },
  ...(Object.keys(REQUISITION_STATUS_LABELS) as RequisitionStatus[]).map((value) => ({
    value,
    label: REQUISITION_STATUS_LABELS[value],
  })),
];

function handleResetFilters() {
  statusFilter.value = "all";
  keyword.value = "";
  dataTable.refresh(true);
}

/* ── 列表 ── */

const columns = computed<ColumnDef<RequisitionBundleListItem>[]>(
  () =>
    [
      { accessorKey: "req_no", header: "需求编号", size: 140 },
      {
        accessorKey: "title",
        header: "职位名称",
        size: 180,
        cell: ({ row }) => h("span", { class: "font-medium" }, row.original.title),
      },
      {
        accessorKey: "org_id",
        header: "部门",
        size: 120,
        cell: ({ row }) => orgNameOf(row.original.org_id),
      },
      {
        accessorKey: "headcount",
        header: "招聘人数",
        size: 90,
      },
      {
        id: "application_count",
        header: "申请明细",
        size: 90,
        cell: ({ row }) => `${row.original.application_count} 行`,
      },
      {
        id: "offer_count",
        header: "Offer（孙）",
        size: 100,
        cell: ({ row }) => `${row.original.offer_count} 个`,
      },
      {
        accessorKey: "priority",
        header: "优先级",
        size: 90,
        cell: ({ row }) =>
          h(
            Badge,
            { variant: REQUISITION_PRIORITY_VARIANTS[row.original.priority] },
            () => REQUISITION_PRIORITY_LABELS[row.original.priority] ?? row.original.priority
          ),
      },
      {
        accessorKey: "status",
        header: "状态",
        size: 90,
        cell: ({ row }) =>
          h(
            Badge,
            { variant: REQUISITION_STATUS_VARIANTS[row.original.status] },
            () => REQUISITION_STATUS_LABELS[row.original.status] ?? row.original.status
          ),
      },
      {
        id: "actions",
        header: "操作",
        size: 110,
        cell: ({ row }) =>
          h(RowActions, {
            actions: [
              {
                key: "detail",
                label: "详情",
                onClick: () => openSheet(row.original.id, false),
              },
              ...(canWrite.value && row.original.status !== "closed"
                ? [
                    {
                      key: "edit",
                      label: "编辑",
                      onClick: () => openSheet(row.original.id, true),
                    },
                  ]
                : []),
            ],
          }),
      },
    ] as ColumnDef<RequisitionBundleListItem>[]
);

const dataTable = useDataTable<RequisitionBundleListItem>({
  columns: columns.value,
  remoteFetchFn: async ({ page, page_size }) => {
    const res = await listRequisitionBundles({
      page,
      page_size,
      status: statusFilter.value === "all" ? undefined : (statusFilter.value as RequisitionStatus),
      keyword: keyword.value || undefined,
    });
    return { data: res.data ?? [], total: res.total || 0 };
  },
});

/* ── 侧滑（新建 / 详情 / 编辑） ── */

const sheetOpen = ref(false);
const sheetId = ref<string | null>(null);
const sheetInitialEdit = ref(false);

function openSheet(id: string | null, initialEdit: boolean) {
  sheetId.value = id;
  sheetInitialEdit.value = initialEdit;
  sheetOpen.value = true;
}

function handleCreate() {
  openSheet(null, false);
}

onMounted(() => {
  void loadReferences();
});
</script>

<template>
  <AppPage
    title="招聘聚合测试"
    description="父（需求）- 子（申请明细）- 孙（Offer）三级对象聚合维护，作为流程测试载体"
  >
    <template #actions>
      <Button variant="outline" data-testid="bundle-refresh" @click="dataTable.refresh()">
        <RefreshCw class="mr-1 h-4 w-4" />
        刷新
      </Button>
      <Button v-if="canWrite" data-testid="bundle-create" @click="handleCreate">
        <Plus class="mr-1 h-4 w-4" />
        新建聚合单
      </Button>
    </template>

    <div
      class="bg-card ring-foreground/10 flex h-full min-h-0 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm"
    >
      <!-- 筛选栏 -->
      <div class="flex shrink-0 flex-wrap items-center gap-2 border-b px-5 py-3">
        <Select
          v-model="statusFilter"
          trigger-class="w-32"
          :options="statusOptions"
          data-testid="bundle-status-filter"
        />
        <Input
          v-model="keyword"
          class="w-44"
          placeholder="职位名称/需求编号"
          data-testid="bundle-keyword-input"
          @keyup.enter="dataTable.refresh(true)"
        />
        <Button variant="outline" size="sm" data-testid="bundle-search" @click="dataTable.refresh(true)">
          搜索
        </Button>
        <Button variant="ghost" size="sm" data-testid="bundle-filter-reset" @click="handleResetFilters">
          重置
        </Button>
      </div>

      <!-- 表格区 -->
      <div class="flex min-h-0 flex-1 flex-col px-5 pt-4">
        <DataTable :data-table="dataTable" :fixed-layout="true" data-testid="bundle-table" />
      </div>
    </div>

    <!-- 聚合单侧滑（父子孙展示 + 新建/编辑表单） -->
    <RequisitionBundleSheet
      v-model:open="sheetOpen"
      :requisition-id="sheetId"
      :initial-edit="sheetInitialEdit"
      :can-write="canWrite"
      :org-name-of="orgNameOf"
      @saved="dataTable.refresh()"
    />
  </AppPage>
</template>
