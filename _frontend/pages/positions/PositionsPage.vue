<script setup lang="ts">
/**
 * 岗位管理页：左组织树筛选 + 筛选栏 + DataTable + 表单弹窗 + 在岗员工抽屉。
 * 删除保护：在岗员工 > 0 不可删（仅可停用），行内删除按钮同步隐藏。
 */
import type { ColumnDef } from "@tanstack/vue-table";
import { computed, h, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import {
  Badge,
  Button,
  DataTable,
  Input,
  Select,
  useDataTable,
} from "@/components";
import { ScrollArea } from "@/components/ui/scroll-area";
import AppPage from "@/framework/layouts/components/AppPage.vue";

import { confirmAction, getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";
import { useUserStore } from "@/framework/stores";

import { deletePosition, listPositions, updatePosition } from "@/hr/api/position";
import { getOrgTree } from "@/hr/api/reference";
import OrgNavTree from "@/hr/components/OrgNavTree.vue";
import PositionFormModal from "@/hr/components/position/PositionFormModal.vue";
import PositionEmployeesDrawer from "@/hr/components/position/PositionEmployeesDrawer.vue";
import PositionRowActions from "@/hr/components/position/PositionRowActions.vue";
import {
  POSITION_STATUS_LABELS,
  POSITION_STATUS_VARIANTS,
  type Position,
  type PositionStatus,
} from "@/hr/types/position";
import type { OrgTreeNode } from "@/hr/types/employee";

const STATUS_OPTIONS = (
  Object.entries(POSITION_STATUS_LABELS) as [PositionStatus, string][]
).map(([value, label]) => ({ value, label }));

const router = useRouter();
const userStore = useUserStore();
const canWrite = computed(() => userStore.hasPermission("hr:position:write"));
const canDelete = computed(() => userStore.hasPermission("hr:position:delete"));

/* ── 组织树 ── */

const orgTree = ref<OrgTreeNode[]>([]);
const selectedOrgId = ref<string>("");

async function loadOrgTree() {
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
  return findOrgNode(orgTree.value, orgId)?.name ?? "--";
}

function handleOrgSelect(node: OrgTreeNode) {
  // 同节点再点取消筛选
  selectedOrgId.value = selectedOrgId.value === node.id ? "" : node.id;
  dataTable.refresh(true);
}

/* ── 筛选 ── */

const keyword = ref("");
const jobLevelFilter = ref("");
const statusFilter = ref("all");

const statusSelectOptions = computed(() => [{ value: "all", label: "全部状态" }, ...STATUS_OPTIONS]);

function handleResetFilters() {
  keyword.value = "";
  jobLevelFilter.value = "";
  statusFilter.value = "all";
  dataTable.refresh(true);
}

/* ── 列表 ── */

const columns = computed<ColumnDef<Position>[]>(() => [
  { accessorKey: "code", header: "岗位编码", size: 120 },
  { accessorKey: "name", header: "岗位名称", size: 150 },
  {
    accessorKey: "org_id",
    header: "所属组织",
    size: 140,
    cell: ({ row }) => h("span", {}, orgNameOf(row.original.org_id)),
  },
  {
    accessorKey: "job_level",
    header: "职级",
    size: 80,
    cell: ({ row }) => row.original.job_level ?? "--",
  },
  {
    accessorKey: "headcount",
    header: "编制数",
    size: 90,
    cell: ({ row }) => row.original.headcount ?? "不限",
  },
  {
    accessorKey: "active_employee_count",
    header: "编制 / 在岗",
    size: 100,
    cell: ({ row }) =>
      `${row.original.headcount ?? "不限"} / ${row.original.active_employee_count}`,
  },
  {
    accessorKey: "status",
    header: "状态",
    size: 90,
    cell: ({ row }) =>
      h(Badge, { variant: POSITION_STATUS_VARIANTS[row.original.status] }, () =>
        POSITION_STATUS_LABELS[row.original.status] ?? row.original.status,
      ),
  },
  {
    id: "actions",
    header: "操作",
    size: 100,
    cell: ({ row }) =>
      h(PositionRowActions, {
        position: row.original,
        canWrite: canWrite.value,
        canDelete: canDelete.value,
        onEdit: (position: Position) => openFormModal("edit", position),
        onEmployees: (position: Position) => openEmployeesDrawer(position),
        onToggleStatus: (position: Position) => toggleStatus(position),
        onRemove: (position: Position) => removePosition(position),
      } as Record<string, unknown>),
  },
] as ColumnDef<Position>[]);

const dataTable = useDataTable<Position>({
  columns: columns.value,
  remoteFetchFn: async ({ page, page_size }) => {
    const res = await listPositions({
      page,
      page_size,
      keyword: keyword.value || undefined,
      org_id: selectedOrgId.value || undefined,
      job_level: jobLevelFilter.value || undefined,
      status: statusFilter.value === "all" ? undefined : (statusFilter.value as PositionStatus),
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

/* ── 弹窗编排 ── */

const formModalOpen = ref(false);
const formMode = ref<"create" | "edit">("create");
const formPosition = ref<Position | null>(null);
const employeesDrawerOpen = ref(false);
const drawerPosition = ref<Position | null>(null);

function openFormModal(mode: "create" | "edit", position: Position | null = null) {
  formMode.value = mode;
  formPosition.value = position;
  formModalOpen.value = true;
}

function openEmployeesDrawer(position: Position) {
  drawerPosition.value = position;
  employeesDrawerOpen.value = true;
}

async function toggleStatus(position: Position) {
  const next: PositionStatus = position.status === "disabled" ? "active" : "disabled";
  const verb = next === "disabled" ? "停用" : "启用";
  if (
    !(await confirmAction(
      `确定${verb}岗位「${position.name}」？停用岗位不可被员工建档与招聘需求选中。`,
    ))
  ) {
    return;
  }
  try {
    await updatePosition(position.id, { status: next });
    notifySuccess(`岗位已${verb}`);
    dataTable.refresh();
  } catch (error) {
    notifyError(error, getErrorMessage(error, `岗位${verb}失败`));
  }
}

async function removePosition(position: Position) {
  if (!(await confirmAction(`确定删除岗位「${position.name}」？该操作不可恢复。`))) return;
  try {
    await deletePosition(position.id);
    notifySuccess("岗位已删除");
    dataTable.refresh();
  } catch (error) {
    // 在岗员工 > 0 时后端拒绝删除，提示只可停用
    notifyError(error, getErrorMessage(error, "删除失败：该岗位存在在岗员工，仅可停用"));
  }
}

/** 在岗员工抽屉「查看员工」→ 员工管理页定位打开详情抽屉 */
function handleViewEmployee(employeeId: string) {
  void router.push({ path: "/hr/employees", query: { employee_id: employeeId } });
}

onMounted(() => {
  void loadOrgTree();
});
</script>

<template>
  <AppPage title="岗位管理" description="岗位档案：职务单元、职级编制与在岗情况的管理">
    <template #actions>
      <Button v-if="canWrite" data-testid="open-create-position" @click="openFormModal('create')">
        新增岗位
      </Button>
    </template>

    <div class="flex h-full min-h-0 gap-4">
      <!-- 左组织树 -->
      <div class="bg-card ring-foreground/10 hidden w-64 shrink-0 flex-col overflow-hidden rounded-xl ring-1 shadow-sm md:flex" data-testid="position-org-panel">
        <div class="text-muted-foreground shrink-0 border-b px-4 py-3 text-xs font-medium">组织架构</div>
        <ScrollArea class="min-h-0 flex-1">
          <div class="p-2">
            <OrgNavTree :organizations="orgTree" :selected-id="selectedOrgId" @select="handleOrgSelect" />
          </div>
        </ScrollArea>
      </div>

      <!-- 右侧列表卡 -->
      <div class="bg-card ring-foreground/10 flex min-w-0 flex-1 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
        <!-- 筛选栏 -->
        <div class="flex shrink-0 flex-wrap items-center gap-2 border-b px-5 py-3">
          <Input
            v-model="keyword"
            class="w-52"
            placeholder="岗位编码/名称"
            data-testid="position-keyword-input"
            @keyup.enter="dataTable.refresh(true)"
          />
          <Input
            v-model="jobLevelFilter"
            class="w-28"
            placeholder="职级"
            data-testid="position-job-level-input"
            @keyup.enter="dataTable.refresh(true)"
          />
          <Select v-model="statusFilter" trigger-class="w-32" :options="statusSelectOptions" data-testid="position-status-filter" />
          <Button variant="outline" size="sm" data-testid="position-search" @click="dataTable.refresh(true)">搜索</Button>
          <Button variant="ghost" size="sm" data-testid="position-filter-reset" @click="handleResetFilters">重置</Button>
        </div>

        <!-- 表格区 -->
        <div class="flex min-h-0 flex-1 flex-col px-5 pt-4">
          <DataTable :data-table="dataTable" :fixed-layout="true" />
        </div>
      </div>
    </div>

    <!-- 岗位表单弹窗 -->
    <PositionFormModal v-model:open="formModalOpen" :mode="formMode" :position="formPosition" @saved="dataTable.refresh()" />

    <!-- 在岗员工抽屉 -->
    <PositionEmployeesDrawer
      v-model:open="employeesDrawerOpen"
      :position="drawerPosition"
      :org-name-of="orgNameOf"
      @view-employee="handleViewEmployee"
    />
  </AppPage>
</template>
