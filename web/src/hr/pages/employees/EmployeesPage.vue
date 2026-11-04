<script setup lang="ts">
/**
 * 员工管理页：四统计卡 + 左组织树 + 筛选/操作区 + DataTable + 详情抽屉与弹窗族。
 * 姓名列点击开抽屉；行操作（编辑/开通账号/办理离职/删除）；mutations 后刷新列表与统计。
 */
import type { ColumnDef } from "@tanstack/vue-table";
import { computed, h, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import {
  Badge,
  Button,
  DataTable,
  Input,
  Select,
  useDataTable,
} from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components";
import { Label } from "@/components";
import { ScrollArea } from "@/components/ui/scroll-area";
import AppPage from "@/framework/layouts/components/AppPage.vue";

import { confirmAction, getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";
import { useUserStore } from "@/framework/stores";

import {
  deleteEmployee,
  getEmployeeStats,
  listEmployees,
  openAccount,
} from "@/hr/api/employee";
import { getOrgTree, getPositionOptions } from "@/hr/api/reference";
import EmployeeChangeModal from "@/hr/components/employee/EmployeeChangeModal.vue";
import EmployeeDetailDrawer from "@/hr/components/employee/EmployeeDetailDrawer.vue";
import EmployeeFormModal from "@/hr/components/employee/EmployeeFormModal.vue";
import EmployeeImportModal from "@/hr/components/employee/EmployeeImportModal.vue";
import EmployeeRowActions from "@/hr/components/employee/EmployeeRowActions.vue";
import FieldDefinitionManager from "@/hr/components/employee/FieldDefinitionManager.vue";
import OrgNavTree from "@/hr/components/OrgNavTree.vue";
import {
  EMPLOYEE_STATUS_LABELS,
  EMPLOYEE_STATUS_VARIANTS,
  type AccountOpenResult,
  type Employee,
  type EmployeeDetail,
  type EmployeeStats,
  type OrgTreeNode,
  type PositionOption,
} from "@/hr/types/employee";

const EMPLOYEE_STATUS_OPTIONS = (
  Object.entries(EMPLOYEE_STATUS_LABELS) as [string, string][]
).map(([value, label]) => ({ value, label }));

const route = useRoute();

const userStore = useUserStore();
const canWrite = computed(() => userStore.hasPermission("hr:employee:write"));
const canDelete = computed(() => userStore.hasPermission("hr:employee:delete"));
const canImport = computed(() => userStore.hasPermission("hr:employee:import"));
const canManageFields = computed(() => userStore.hasPermission("hr:field_definition:write"));

/* ── 统计卡 ── */

const stats = ref<EmployeeStats | null>(null);

const statCards = computed(() => [
  { key: "active", label: "在编人数", value: stats.value?.active_count ?? 0 },
  { key: "probation", label: "试用期人数", value: stats.value?.probation_count ?? 0 },
  { key: "month_hired", label: "本月新入职", value: stats.value?.month_hired_count ?? 0 },
  {
    key: "turnover",
    label: "离职率",
    value: `${((stats.value?.turnover_rate ?? 0) * 100).toFixed(1)}%`,
  },
]);

async function loadStats() {
  try {
    const res = await getEmployeeStats(selectedOrgId.value || undefined);
    stats.value = res.data ?? null;
  } catch {
    stats.value = null;
  }
}

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

function handleOrgSelect(node: OrgTreeNode) {
  // 同节点再点取消筛选
  selectedOrgId.value = selectedOrgId.value === node.id ? "" : node.id;
  void loadStats();
  dataTable.refresh(true);
}

/* ── 筛选 ── */

const keyword = ref("");
const statusFilter = ref("all");
const positionFilter = ref("all");
const jobLevelFilter = ref("");
const positionOptions = ref<PositionOption[]>([]);

async function loadPositionOptions() {
  try {
    const res = await getPositionOptions();
    positionOptions.value = res.data ?? [];
  } catch {
    positionOptions.value = [];
  }
}

const statusSelectOptions = computed(() => [{ value: "all", label: "全部状态" }, ...EMPLOYEE_STATUS_OPTIONS]);
const positionSelectOptions = computed(() => [
  { value: "all", label: "全部岗位" },
  ...positionOptions.value.map((p) => ({ value: p.id, label: p.name })),
]);

function handleResetFilters() {
  keyword.value = "";
  statusFilter.value = "all";
  positionFilter.value = "all";
  jobLevelFilter.value = "";
  dataTable.refresh(true);
}

/* ── 列表 ── */

function openDetail(row: Employee) {
  detailEmployeeId.value = row.id;
  detailOpen.value = true;
}

/** 当前页数据快照（详情抽屉切换条数据源） */
const listRows = ref<Employee[]>([]);

const columns = computed<ColumnDef<Employee>[]>(() => [
  { accessorKey: "employee_no", header: "工号", size: 110 },
  {
    accessorKey: "name",
    header: "姓名",
    size: 130,
    cell: ({ row }) =>
      h(
        "button",
        {
          class: "text-primary hover:text-primary/80 hover:underline",
          "data-testid": "employee-name-link",
          type: "button",
          onClick: () => openDetail(row.original),
        },
        () => row.original.name,
      ),
  },
  {
    accessorKey: "org_id",
    header: "组织",
    size: 140,
    cell: ({ row }) => h("span", {}, orgNameOf(row.original.org_id)),
  },
  {
    accessorKey: "position_id",
    header: "岗位",
    size: 120,
    cell: ({ row }) => h("span", {}, positionNameOf(row.original.position_id)),
  },
  { accessorKey: "job_level", header: "职级", size: 80 },
  {
    accessorKey: "status",
    header: "状态",
    size: 90,
    cell: ({ row }) =>
      h(Badge, { variant: EMPLOYEE_STATUS_VARIANTS[row.original.status] }, () =>
        EMPLOYEE_STATUS_LABELS[row.original.status] ?? row.original.status,
      ),
  },
  { accessorKey: "hire_date", header: "入职日期", size: 110 },
  {
    id: "actions",
    header: "操作",
    size: 100,
    cell: ({ row }) =>
      h(EmployeeRowActions, {
        employee: row.original,
        canWrite: canWrite.value,
        canDelete: canDelete.value,
        onEdit: (employee: Employee) => openFormModal("edit", employee),
        onOpenAccount: (employee: Employee) => openAccountFor(employee),
        onOffboard: (employee: Employee) => openChangeModal(employee, "offboard"),
        onRemove: (employee: Employee) => removeEmployee(employee),
      } as Record<string, unknown>),
  },
] as ColumnDef<Employee>[]);

const dataTable = useDataTable<Employee>({
  columns: columns.value,
  remoteFetchFn: async ({ page, page_size }) => {
    const res = await listEmployees({
      page,
      page_size,
      keyword: keyword.value || undefined,
      status: statusFilter.value === "all" ? undefined : (statusFilter.value as Employee["status"]),
      org_id: selectedOrgId.value || undefined,
      position_id: positionFilter.value === "all" ? undefined : positionFilter.value,
      job_level: jobLevelFilter.value || undefined,
    });
    const rows = res.data ?? [];
    listRows.value = rows;
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

function orgNameOf(orgId: string | null): string {
  if (!orgId) return "--";
  const found = findOrgNode(orgTree.value, orgId);
  return found?.name ?? "--";
}

function findOrgNode(nodes: OrgTreeNode[], id: string): OrgTreeNode | null {
  for (const node of nodes) {
    if (node.id === id) return node;
    const child = findOrgNode(node.children ?? [], id);
    if (child) return child;
  }
  return null;
}

function positionNameOf(positionId: string | null): string {
  if (!positionId) return "--";
  return positionOptions.value.find((p) => p.id === positionId)?.name ?? "--";
}

function refreshAll() {
  void loadStats();
  dataTable.refresh();
}

/* ── 弹窗编排 ── */

const formModalOpen = ref(false);
const formMode = ref<"create" | "edit">("create");
const formEmployee = ref<EmployeeDetail | Employee | null>(null);
const importModalOpen = ref(false);
const changeModalOpen = ref(false);
const changeEmployee = ref<Employee | null>(null);
const changeInitialType = ref<"probate" | "offboard">("probate");
const fieldManagerOpen = ref(false);
const detailOpen = ref(false);
const detailEmployeeId = ref<string | null>(null);
const accountResult = ref<AccountOpenResult | null>(null);

function openFormModal(mode: "create" | "edit", employee: Employee | null = null) {
  formMode.value = mode;
  formEmployee.value = employee;
  formModalOpen.value = true;
}

function openChangeModal(employee: Employee, type: "probate" | "offboard") {
  changeEmployee.value = employee;
  changeInitialType.value = type;
  changeModalOpen.value = true;
}

async function openAccountFor(employee: Employee) {
  try {
    const res = await openAccount(employee.id);
    accountResult.value = res.data ?? null;
    refreshAll();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "账号开通失败"));
  }
}

async function removeEmployee(employee: Employee) {
  if (!(await confirmAction(`确定删除员工「${employee.name}」？该操作不可恢复。`))) return;
  try {
    await deleteEmployee(employee.id);
    notifySuccess("员工已删除");
    refreshAll();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "删除失败"));
  }
}

async function copyAccountResult() {
  if (!accountResult.value) return;
  try {
    await navigator.clipboard.writeText(
      `账号：${accountResult.value.username}\n初始密码：${accountResult.value.initial_password}`,
    );
    notifySuccess("已复制账号与初始密码");
  } catch {
    notifyError(new Error("复制失败，请手动复制"));
  }
}

onMounted(() => {
  void loadOrgTree();
  void loadPositionOptions();
  void loadStats();
  // 在岗员工抽屉「查看员工」跳转定位：/hr/employees?employee_id=xxx
  const target = route.query.employee_id;
  if (typeof target === "string" && target) {
    detailEmployeeId.value = target;
    detailOpen.value = true;
  }
});
</script>

<template>
  <AppPage title="员工管理" description="员工花名册：建档、异动、合同、材料与扩展属性的一站式管理">
    <template #actions>
      <Button v-if="canManageFields" variant="outline" data-testid="open-field-manager" @click="fieldManagerOpen = true">
        属性定义管理
      </Button>
      <Button v-if="canImport" variant="outline" data-testid="open-import-modal" @click="importModalOpen = true">
        批量导入
      </Button>
      <Button v-if="canWrite" data-testid="open-create-modal" @click="openFormModal('create')">入职建档</Button>
    </template>

    <div class="flex h-full min-h-0 flex-col gap-4">
      <!-- 统计卡 -->
      <div class="grid shrink-0 grid-cols-2 gap-4 lg:grid-cols-4" data-testid="employee-stat-cards">
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

      <!-- 左树 + 右表 -->
      <div class="flex min-h-0 flex-1 gap-4">
        <!-- 左组织树 -->
        <div class="bg-card ring-foreground/10 hidden w-64 shrink-0 flex-col overflow-hidden rounded-xl ring-1 shadow-sm md:flex" data-testid="employee-org-panel">
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
              placeholder="姓名/工号/手机号"
              data-testid="employee-keyword-input"
              @keyup.enter="dataTable.refresh(true)"
            />
            <Select v-model="statusFilter" trigger-class="w-32" :options="statusSelectOptions" data-testid="employee-status-select" />
            <Select v-model="positionFilter" trigger-class="w-36" :options="positionSelectOptions" data-testid="employee-position-select" />
            <Input v-model="jobLevelFilter" class="w-28" placeholder="职级" data-testid="employee-job-level-input" @keyup.enter="dataTable.refresh(true)" />
            <Button variant="outline" size="sm" data-testid="employee-search" @click="dataTable.refresh(true)">搜索</Button>
            <Button variant="ghost" size="sm" data-testid="employee-filter-reset" @click="handleResetFilters">重置</Button>
          </div>

          <!-- 表格区 -->
          <div class="flex min-h-0 flex-1 flex-col px-5 pt-4">
            <DataTable :data-table="dataTable" :fixed-layout="true" />
          </div>
        </div>
      </div>
    </div>

    <!-- 入职建档 / 编辑 -->
    <EmployeeFormModal v-model:open="formModalOpen" :mode="formMode" :employee="formEmployee" @saved="refreshAll" />

    <!-- 批量导入 -->
    <EmployeeImportModal v-model:open="importModalOpen" @imported="refreshAll" />

    <!-- 人事异动（列表行办理离职直达 offboard） -->
    <EmployeeChangeModal
      v-model:open="changeModalOpen"
      :employee="changeEmployee"
      :initial-type="changeInitialType"
      @saved="refreshAll"
    />

    <!-- 属性定义管理 -->
    <FieldDefinitionManager v-model:open="fieldManagerOpen" />

    <!-- 详情抽屉 -->
    <EmployeeDetailDrawer
      v-model:open="detailOpen"
      :employee-id="detailEmployeeId"
      :employees="listRows"
      @refresh="refreshAll"
      @switch="(employee) => (detailEmployeeId = employee.id)"
    />

    <!-- 账号开通结果 -->
    <Dialog :open="Boolean(accountResult)" @update:open="(value: boolean) => { if (!value) accountResult = null; }">
      <DialogContent class="sm:max-w-sm" data-testid="page-account-result-dialog">
        <DialogHeader>
          <DialogTitle>账号开通成功</DialogTitle>
          <DialogDescription>初始密码仅本次展示，请立即复制并告知员工。</DialogDescription>
        </DialogHeader>
        <div v-if="accountResult" class="flex flex-col gap-2 rounded-md border p-3 text-sm">
          <div class="flex justify-between">
            <Label>登录账号</Label>
            <span class="font-mono">{{ accountResult.username }}</span>
          </div>
          <div class="flex justify-between">
            <Label>初始密码</Label>
            <span class="font-mono">{{ accountResult.initial_password }}</span>
          </div>
        </div>
        <div class="flex justify-end gap-2">
          <Button variant="outline" @click="copyAccountResult">复制</Button>
          <Button @click="accountResult = null">我已保存</Button>
        </div>
      </DialogContent>
    </Dialog>
  </AppPage>
</template>
