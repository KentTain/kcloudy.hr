<script setup lang="ts">
/**
 * 异动管理页：跨员工异动流水检索（类型/时间段/组织/关键词）+ 前后对比侧滑
 * + 发起异动（员工选择 → EmployeeChangeModal）。
 */
import type { ColumnDef } from "@tanstack/vue-table";
import { computed, h, onMounted, ref, watch } from "vue";
import {
  Badge,
  Button,
  DataTable,
  DateInput,
  DescriptionList,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  OrganizationSelect,
  PeopleSelectDialog,
  Select,
  Table,
  useDataTable,
} from "@/components";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import AppPage from "@/framework/layouts/components/AppPage.vue";
import { useUserStore } from "@/framework/stores";
import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { listChangeRecords, transferChangeRecord } from "@/hr/api/change";
import { listEmployees } from "@/hr/api/employee";
import { getOrgTree, getPositionOptions } from "@/hr/api/reference";
import EmployeeChangeModal from "@/hr/components/employee/EmployeeChangeModal.vue";
import {
  CHANGE_TYPE_LABELS,
  type ChangeRecord,
  type ChangeType,
  type Employee,
  MANUAL_CHANGE_TYPES,
  type OrgTreeNode,
} from "@/hr/types/employee";
import { changeDiffLines } from "@/hr/utils/change";

const userStore = useUserStore();
const canWrite = computed(() => userStore.hasPermission("hr:employee_change:write"));
const canTransfer = computed(() => userStore.hasPermission("hr:employee_change:transfer"));

/* ── 参照解析（员工/组织/岗位 ID → 名称） ── */

const employeeMap = ref<Map<string, Employee>>(new Map());
const orgTree = ref<OrgTreeNode[]>([]);
const positionOptions = ref<{ id: string; name: string }[]>([]);

async function loadReferences() {
  try {
    const res = await listEmployees({ page: 1, page_size: 200 });
    const rows = res.data ?? [];
    employeeMap.value = new Map(rows.map((employee) => [employee.id, employee]));
  } catch {
    employeeMap.value = new Map();
  }
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

function employeeLabelOf(employeeId: string): string {
  const employee = employeeMap.value.get(employeeId);
  return employee ? `${employee.employee_no} ${employee.name}` : employeeId;
}

function resolveSnapshotName(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "--";
  if (key === "org_id") return findOrgNode(orgTree.value, String(value))?.name ?? String(value);
  if (key === "position_id") {
    return positionOptions.value.find((p) => p.id === String(value))?.name ?? String(value);
  }
  return String(value);
}

/* ── 筛选 ── */

const changeTypeFilter = ref("all");
const orgIds = ref<string[]>([]);
const startDate = ref("");
const endDate = ref("");
const keyword = ref("");

const changeTypeOptions = [
  { value: "all", label: "全部类型" },
  ...MANUAL_CHANGE_TYPES.concat("hire" as ChangeType).map((value) => ({
    value,
    label: CHANGE_TYPE_LABELS[value],
  })),
];

function handleResetFilters() {
  changeTypeFilter.value = "all";
  orgIds.value = [];
  startDate.value = "";
  endDate.value = "";
  keyword.value = "";
  dataTable.refresh(true);
}

/* ── 列表 ── */

const columns = computed<ColumnDef<ChangeRecord>[]>(
  () =>
    [
      {
        accessorKey: "employee_id",
        header: "员工",
        size: 150,
        cell: ({ row }) => employeeLabelOf(row.original.employee_id),
      },
      {
        accessorKey: "change_type",
        header: "异动类型",
        size: 100,
        cell: ({ row }) =>
          h(
            Badge,
            { variant: "secondary" },
            () => CHANGE_TYPE_LABELS[row.original.change_type] ?? row.original.change_type
          ),
      },
      {
        id: "summary",
        header: "变更摘要",
        size: 240,
        cell: ({ row }) =>
          h(
            "span",
            { class: "text-muted-foreground" },
            changeDiffLines(row.original, resolveSnapshotName).join("；")
          ),
      },
      { accessorKey: "effective_date", header: "生效日期", size: 110 },
      {
        accessorKey: "operator_id",
        header: "操作人",
        size: 120,
        cell: ({ row }) => row.original.operator_id ?? "--",
      },
      {
        id: "actions",
        header: "操作",
        size: 120,
        cell: ({ row }) =>
          h("div", { class: "flex items-center gap-3" }, [
            h(
              "button",
              {
                class: "text-primary hover:text-primary/80 hover:underline",
                "data-testid": "change-detail-link",
                type: "button",
                onClick: () => openDetail(row.original),
              },
              () => "详情"
            ),
            ...(canTransfer.value
              ? [
                  h(
                    "button",
                    {
                      class: "text-primary hover:text-primary/80 hover:underline",
                      "data-testid": `change-transfer-${row.original.id}`,
                      type: "button",
                      onClick: () => openTransfer(row.original),
                    },
                    () => "移交"
                  ),
                ]
              : []),
          ]),
      },
    ] as ColumnDef<ChangeRecord>[]
);

const dataTable = useDataTable<ChangeRecord>({
  columns: columns.value,
  remoteFetchFn: async ({ page, page_size }) => {
    const res = await listChangeRecords({
      page,
      page_size,
      change_type:
        changeTypeFilter.value === "all" ? undefined : (changeTypeFilter.value as ChangeType),
      org_id: orgIds.value[0] || undefined,
      start_date: startDate.value || undefined,
      end_date: endDate.value || undefined,
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

/* ── 详情侧滑（前后对比） ── */

const detailOpen = ref(false);
const detailRecord = ref<ChangeRecord | null>(null);
const detailDescriptionItems = computed(() => {
  const record = detailRecord.value;
  if (!record) return [];
  return [
    { label: "员工", value: employeeLabelOf(record.employee_id) },
    { label: "异动类型", value: CHANGE_TYPE_LABELS[record.change_type] ?? record.change_type },
    { label: "生效日期", value: record.effective_date },
    { label: "操作人", value: record.operator_id ?? "--" },
  ];
});

const detailDiffLines = computed(() =>
  detailRecord.value ? changeDiffLines(detailRecord.value, resolveSnapshotName) : []
);

function openDetail(record: ChangeRecord) {
  detailRecord.value = record;
  detailOpen.value = true;
}

/* ── 异动记录移交（数据归属 D2） ── */

const transferOpen = ref(false);
const transferTarget = ref<ChangeRecord | null>(null);
const transferOwnerIds = ref<string[]>([]);

function openTransfer(record: ChangeRecord) {
  transferTarget.value = record;
  transferOwnerIds.value = [];
  transferOpen.value = true;
}

async function handleTransferConfirm(
  userIds: string[],
  users: { nickname?: string | null; username?: string }[]
) {
  const target = transferTarget.value;
  if (!target || userIds.length === 0) return;
  try {
    await transferChangeRecord(target.id, userIds[0]);
    const targetName = users[0]?.nickname || users[0]?.username;
    notifySuccess(targetName ? `已移交至 ${targetName}` : "移交成功");
    dataTable.refresh();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "移交失败"));
  }
}

/* ── 发起异动：员工选择 → ChangeModal ── */

const pickerOpen = ref(false);
const pickerKeyword = ref("");
const pickerRows = ref<Employee[]>([]);
const pickerLoading = ref(false);
const changeModalOpen = ref(false);
const changeEmployee = ref<Employee | null>(null);

async function searchPickerEmployees() {
  pickerLoading.value = true;
  try {
    const res = await listEmployees({
      page: 1,
      page_size: 20,
      keyword: pickerKeyword.value || undefined,
    });
    pickerRows.value = res.data ?? [];
  } catch (error) {
    notifyError(error, getErrorMessage(error, "员工搜索失败"));
  } finally {
    pickerLoading.value = false;
  }
}

watch(pickerOpen, async (value) => {
  if (!value) return;
  pickerKeyword.value = "";
  await searchPickerEmployees();
});

function pickEmployee(employee: Employee) {
  pickerOpen.value = false;
  changeEmployee.value = employee;
  changeModalOpen.value = true;
}

onMounted(() => {
  void loadReferences();
});
</script>

<template>
  <AppPage title="异动管理" description="员工入转调离流水检索：前后快照对比与异动发起">
    <template #actions>
      <Button v-if="canWrite" data-testid="open-change-picker" @click="pickerOpen = true">发起异动</Button>
    </template>

    <div class="bg-card ring-foreground/10 flex h-full min-h-0 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
      <!-- 筛选栏 -->
      <div class="flex shrink-0 flex-wrap items-center gap-2 border-b px-5 py-3">
        <Select v-model="changeTypeFilter" trigger-class="w-32" :options="changeTypeOptions" data-testid="change-type-filter" />
        <OrganizationSelect v-model="orgIds" :multiple="false" placeholder="按异动后组织" class="w-44" data-testid="change-org-filter" />
        <DateInput v-model="startDate" placeholder="生效起" class="w-36" data-testid="change-start-date" />
        <span class="text-muted-foreground text-xs">至</span>
        <DateInput v-model="endDate" placeholder="生效止" class="w-36" data-testid="change-end-date" />
        <Input
          v-model="keyword"
          class="w-44"
          placeholder="工号/姓名"
          data-testid="change-keyword-input"
          @keyup.enter="dataTable.refresh(true)"
        />
        <Button variant="outline" size="sm" data-testid="change-search" @click="dataTable.refresh(true)">搜索</Button>
        <Button variant="ghost" size="sm" data-testid="change-filter-reset" @click="handleResetFilters">重置</Button>
      </div>

      <!-- 表格区 -->
      <div class="flex min-h-0 flex-1 flex-col px-5 pt-4">
        <DataTable :data-table="dataTable" :fixed-layout="true" />
      </div>
    </div>

    <!-- 员工选择弹窗（发起异动前置） -->
    <Dialog :open="pickerOpen" @update:open="pickerOpen = $event">
      <DialogContent class="sm:max-w-lg" data-testid="employee-picker-dialog">
        <DialogHeader>
          <DialogTitle>选择员工</DialogTitle>
          <DialogDescription>检索员工后点击行内「选择」发起异动。</DialogDescription>
        </DialogHeader>
        <div class="flex items-center gap-2">
          <Input
            v-model="pickerKeyword"
            class="flex-1"
            placeholder="姓名/工号/手机号"
            data-testid="employee-picker-keyword"
            @keyup.enter="searchPickerEmployees"
          />
          <Button variant="outline" size="sm" data-testid="employee-picker-search" @click="searchPickerEmployees">搜索</Button>
        </div>
        <div class="max-h-72 overflow-auto rounded-md border">
          <Table
            :columns="[
              { key: 'employee_no', title: '工号', width: '110px' },
              { key: 'name', title: '姓名', width: '110px' },
              { key: 'job_level', title: '职级', width: '80px' },
              { key: 'actions', title: '操作', width: '80px', align: 'right' },
            ]"
            :data="pickerRows"
            :loading="pickerLoading"
            empty-text="无匹配员工"
          >
            <template #actions="{ row }">
              <Button
                variant="link"
                size="sm"
                class="h-auto p-0"
                :data-testid="`picker-pick-${(row as Employee).id}`"
                @click="pickEmployee(row as Employee)"
              >
                选择
              </Button>
            </template>
          </Table>
        </div>
      </DialogContent>
    </Dialog>

    <!-- 发起异动弹窗 -->
    <EmployeeChangeModal
      v-model:open="changeModalOpen"
      :employee="changeEmployee"
      @saved="dataTable.refresh()"
    />

    <!-- 异动记录移交弹窗 -->
    <PeopleSelectDialog
      v-model:open="transferOpen"
      v-model="transferOwnerIds"
      :multiple="false"
      title="移交异动记录"
      confirm-text="确认移交"
      @confirm="handleTransferConfirm"
    />

    <!-- 异动详情侧滑（前后对比） -->
    <Sheet :open="detailOpen" @update:open="detailOpen = $event">
      <SheetContent side="right" class="flex w-full flex-col gap-0 sm:max-w-lg" data-testid="change-detail-drawer">
        <SheetHeader class="shrink-0 border-b px-5 py-4">
          <SheetTitle>异动详情</SheetTitle>
          <SheetDescription>变更字段前后快照对比</SheetDescription>
        </SheetHeader>
        <div v-if="detailRecord" class="flex min-h-0 flex-1 flex-col gap-4 overflow-auto px-5 py-4">
          <DescriptionList :items="detailDescriptionItems" :columns="2" data-testid="change-detail-meta" />
          <div class="flex flex-col gap-2" data-testid="change-detail-diff">
            <p class="text-muted-foreground text-xs font-medium">变更对比</p>
            <div
              v-for="line in detailDiffLines"
              :key="line"
              class="rounded-md border px-3 py-2 text-sm"
            >
              {{ line }}
            </div>
            <p v-if="!detailDiffLines.length" class="text-muted-foreground text-sm">无字段级差异记录</p>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  </AppPage>
</template>
