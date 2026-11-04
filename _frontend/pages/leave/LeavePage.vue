<script setup lang="ts">
/**
 * 假勤管理页：三页签承载假期类型 / 请假单 / 假期余额（路由 16 叶契约，
 * 明细一律页内承载）。请假单支持筛选与审批（通过/驳回），假期余额支持
 * 按年度筛选与总额度调整；假期类型为字典维护（编码创建后不可改）。
 */
import type { ColumnDef } from "@tanstack/vue-table";
import { computed, h, onMounted, ref } from "vue";

import {
  Badge,
  Button,
  DataTable,
  DateInput,
  Input,
  OrganizationSelect,
  PeopleSelectDialog,
  Select,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
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

import {
  deleteLeaveType,
  listLeaveBalances,
  listLeaveRequests,
  listLeaveTypes,
  transferLeaveRequest,
  updateLeaveType,
} from "@/hr/api/leave";
import { getOrgTree } from "@/hr/api/reference";
import LeaveApproveModal from "@/hr/components/leave/LeaveApproveModal.vue";
import LeaveBalanceAdjustModal from "@/hr/components/leave/LeaveBalanceAdjustModal.vue";
import LeaveTypeFormModal from "@/hr/components/leave/LeaveTypeFormModal.vue";
import type { OrgTreeNode } from "@/hr/types/employee";
import {
  LEAVE_QUOTA_RULE_LABELS,
  LEAVE_REQUEST_STATUS_LABELS,
  LEAVE_REQUEST_STATUS_VARIANTS,
  LEAVE_TYPE_STATUS_LABELS,
  LEAVE_TYPE_STATUS_VARIANTS,
  LEAVE_UNIT_LABELS,
  type LeaveBalance,
  type LeaveBalanceQuery,
  type LeaveRequest,
  type LeaveRequestQuery,
  type LeaveRequestStatus,
  type LeaveType,
  type LeaveTypeQuery,
} from "@/hr/types/leave";

const userStore = useUserStore();
const canWrite = computed(() => userStore.hasPermission("hr:leave:write"));
const canApprove = computed(() => userStore.hasPermission("hr:leave:approve"));
const canTransfer = computed(() => userStore.hasPermission("hr:leave:transfer"));

/* ── 共享参照数据 ── */

const orgTree = ref<OrgTreeNode[]>([]);
const leaveTypes = ref<LeaveType[]>([]);

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

async function loadLeaveTypes() {
  try {
    const res = await listLeaveTypes({ page: 1, page_size: 200 });
    leaveTypes.value = res.data ?? [];
  } catch (error) {
    notifyError(error, getErrorMessage(error, "假期类型加载失败"));
  }
}

const leaveTypeOptions = computed(() =>
  leaveTypes.value.map((t) => ({ value: t.id, label: t.name }))
);

function unitText(type: LeaveType | null | undefined): string {
  return type ? LEAVE_UNIT_LABELS[type.unit] : "--";
}

/** 信封适配：data 裸数组 + 顶层 total */
function envelope<T>(
  res: {
    code: number;
    data?: T[] | null;
    msg?: string;
    page?: number;
    page_size?: number;
    total?: number;
  },
  page: number,
  pageSize: number
) {
  return {
    code: res.code,
    data: res.data ?? [],
    msg: res.msg,
    page: res.page || page,
    page_size: res.page_size || pageSize,
    total: res.total || 0,
  };
}

const ALL = "__all__";

/** 激活页签（非激活页签的 useDataTable 以 enabled 门控，避免挂载即发无用请求） */
const activeTab = ref("types");

const typeColumns = ref<ColumnDef<LeaveType>[]>([
  { accessorKey: "code", header: "编码", size: 140 },
  { accessorKey: "name", header: "名称", size: 120 },
  { id: "unit", header: "单位", size: 80, cell: ({ row }) => LEAVE_UNIT_LABELS[row.original.unit] },
  {
    id: "paid",
    header: "带薪",
    size: 80,
    cell: ({ row }) => (row.original.paid ? "是" : "否"),
  },
  {
    accessorKey: "quota_rule",
    header: "额度规则",
    size: 140,
    cell: ({ row }) => LEAVE_QUOTA_RULE_LABELS[row.original.quota_rule],
  },
  {
    accessorKey: "default_quota",
    header: "默认额度",
    size: 100,
    cell: ({ row }) =>
      row.original.default_quota == null
        ? "--"
        : `${row.original.default_quota}${LEAVE_UNIT_LABELS[row.original.unit]}`,
  },
  {
    accessorKey: "status",
    header: "状态",
    size: 90,
    cell: ({ row }) =>
      h(
        Badge,
        { variant: LEAVE_TYPE_STATUS_VARIANTS[row.original.status] },
        () => LEAVE_TYPE_STATUS_LABELS[row.original.status]
      ),
  },
  {
    id: "actions",
    header: "操作",
    size: 200,
    cell: ({ row }) => {
      const item = row.original;
      const buttons = [] as ReturnType<typeof h>[];
      if (canWrite.value) {
        buttons.push(
          h(
            Button,
            {
              variant: "ghost",
              size: "sm",
              "data-testid": `leave-type-edit-${item.code}`,
              onClick: () => openTypeForm(item),
            },
            () => "编辑"
          )
        );
        buttons.push(
          h(
            Button,
            {
              variant: "ghost",
              size: "sm",
              "data-testid": `leave-type-toggle-${item.code}`,
              onClick: () => toggleTypeStatus(item),
            },
            () => (item.status === "enabled" ? "停用" : "启用")
          )
        );
        buttons.push(
          h(
            Button,
            {
              variant: "ghost",
              size: "sm",
              "data-testid": `leave-type-delete-${item.code}`,
              onClick: () => removeType(item),
            },
            () => "删除"
          )
        );
      }
      return h("div", { class: "flex items-center gap-1" }, buttons);
    },
  },
] as ColumnDef<LeaveType>[]);

const typeDataTable = useDataTable<LeaveType>({
  columns: typeColumns.value,
  remoteFetchFn: async ({ page, page_size }) => {
    const query: LeaveTypeQuery = { page, page_size };
    const res = await listLeaveTypes(query);
    return envelope<LeaveType>(res, page, page_size);
  },
});

const typeFormOpen = ref(false);
const typeFormTarget = ref<LeaveType | null>(null);

function openTypeForm(item: LeaveType | null) {
  typeFormTarget.value = item;
  typeFormOpen.value = true;
}

async function toggleTypeStatus(item: LeaveType) {
  const next = item.status === "enabled" ? "disabled" : "enabled";
  const message =
    next === "disabled"
      ? `确定停用「${item.name}」？停用后不可发起新请假，历史请假单不受影响。`
      : `确定启用「${item.name}」？启用后员工可重新发起该类请假。`;
  const confirmed = await confirmAction(message);
  if (!confirmed) return;
  try {
    await updateLeaveType(item.id, { status: next });
    notifySuccess(next === "disabled" ? "假期类型已停用" : "假期类型已启用");
    typeDataTable.refresh();
    void loadLeaveTypes();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "状态变更失败"));
  }
}

async function removeType(item: LeaveType) {
  const confirmed = await confirmAction(
    `确定删除「${item.name}」？已被请假单或余额引用的类型无法删除，建议改为停用。`
  );
  if (!confirmed) return;
  try {
    await deleteLeaveType(item.id);
    notifySuccess("假期类型已删除");
    typeDataTable.refresh();
    void loadLeaveTypes();
  } catch {
    notifyError(new Error("该假期类型已被引用，无法删除，建议改为停用"));
  }
}

function refreshTypes() {
  typeDataTable.refresh();
  void loadLeaveTypes();
}

/* ── 页签二：请假单 ── */

const reqStatus = ref<LeaveRequestStatus | typeof ALL>(ALL);
const reqTypeId = ref<string | typeof ALL>(ALL);
const reqOrgIds = ref<string[]>([]);
const reqKeyword = ref("");
const reqDateFrom = ref("");
const reqDateTo = ref("");

const reqStatusOptions = (["pending", "approved", "rejected", "cancelled"] as const).map(
  (value) => ({ value, label: LEAVE_REQUEST_STATUS_LABELS[value] })
);
const statusFilterOptions = [{ value: ALL, label: "全部状态" }, ...reqStatusOptions];
const typeFilterOptions = computed(() => [
  { value: ALL, label: "全部类型" },
  ...leaveTypeOptions.value,
]);

const reqColumns = ref<ColumnDef<LeaveRequest>[]>([
  { accessorKey: "employee_no", header: "工号", size: 100 },
  { accessorKey: "employee_name", header: "姓名", size: 100 },
  { id: "org", header: "部门", size: 110, cell: ({ row }) => orgNameOf(row.original.org_id) },
  {
    id: "leave_type",
    header: "假期类型",
    size: 100,
    cell: ({ row }) => row.original.leave_type_name ?? "--",
  },
  {
    id: "range",
    header: "起止时间",
    size: 240,
    cell: ({ row }) =>
      `${row.original.start_time.replace("T", " ")} ~ ${row.original.end_time.replace("T", " ")}`,
  },
  {
    id: "duration",
    header: "时长",
    size: 90,
    cell: ({ row }) =>
      `${row.original.duration}${row.original.unit ? LEAVE_UNIT_LABELS[row.original.unit] : ""}`,
  },
  {
    accessorKey: "reason",
    header: "事由",
    cell: ({ row }) => row.original.reason || "--",
  },
  {
    accessorKey: "status",
    header: "状态",
    size: 90,
    cell: ({ row }) =>
      h(
        Badge,
        { variant: LEAVE_REQUEST_STATUS_VARIANTS[row.original.status] },
        () => LEAVE_REQUEST_STATUS_LABELS[row.original.status]
      ),
  },
  {
    id: "actions",
    header: "操作",
    size: 150,
    cell: ({ row }) => {
      const item = row.original;
      const buttons = [] as ReturnType<typeof h>[];
      if (item.status === "pending" && canApprove.value) {
        buttons.push(
          h(
            Button,
            {
              variant: "ghost",
              size: "sm",
              "data-testid": `leave-approve-${item.id}`,
              onClick: () => openApprove(item),
            },
            () => "审批"
          )
        );
      }
      if (item.status === "pending" && canTransfer.value) {
        buttons.push(
          h(
            Button,
            {
              variant: "ghost",
              size: "sm",
              "data-testid": `leave-transfer-${item.id}`,
              onClick: () => openTransfer(item),
            },
            () => "移交"
          )
        );
      }
      if (buttons.length === 0) {
        return h("span", { class: "text-muted-foreground text-xs" }, "--");
      }
      return h("div", { class: "flex items-center gap-1" }, buttons);
    },
  },
] as ColumnDef<LeaveRequest>[]);

const reqDataTable = useDataTable<LeaveRequest>({
  columns: reqColumns.value,
  enabled: () => activeTab.value === "requests",
  remoteFetchFn: async ({ page, page_size }) => {
    const query: LeaveRequestQuery = {
      page,
      page_size,
      status: reqStatus.value === ALL ? undefined : reqStatus.value,
      leave_type_id: reqTypeId.value === ALL ? undefined : reqTypeId.value,
      org_id: reqOrgIds.value[0] || undefined,
      keyword: reqKeyword.value || undefined,
      date_from: reqDateFrom.value || undefined,
      date_to: reqDateTo.value || undefined,
    };
    const res = await listLeaveRequests(query);
    return envelope<LeaveRequest>(res, page, page_size);
  },
});

function handleReqSearch() {
  reqDataTable.refresh(true);
}

function handleReqReset() {
  reqStatus.value = ALL;
  reqTypeId.value = ALL;
  reqOrgIds.value = [];
  reqKeyword.value = "";
  reqDateFrom.value = "";
  reqDateTo.value = "";
  reqDataTable.refresh(true);
}

const approveOpen = ref(false);
const approveTarget = ref<LeaveRequest | null>(null);

function openApprove(item: LeaveRequest) {
  approveTarget.value = item;
  approveOpen.value = true;
}

/* ── 请假单移交（数据归属 D2） ── */

const transferOpen = ref(false);
const transferTarget = ref<LeaveRequest | null>(null);
const transferOwnerIds = ref<string[]>([]);

function openTransfer(item: LeaveRequest) {
  transferTarget.value = item;
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
    await transferLeaveRequest(target.id, userIds[0]);
    const targetName = users[0]?.nickname || users[0]?.username;
    notifySuccess(targetName ? `已移交至 ${targetName}` : "移交成功");
    reqDataTable.refresh();
  } catch (error) {
    notifyError(getErrorMessage(error, "移交失败"));
  }
}

/* ── 页签三：假期余额 ── */

const currentYear = new Date().getFullYear();
const balYear = ref<string>(String(currentYear));
const balTypeId = ref<string | typeof ALL>(ALL);
const balOrgIds = ref<string[]>([]);
const balKeyword = ref("");

const yearOptions = [currentYear, currentYear - 1, currentYear - 2].map((year) => ({
  value: String(year),
  label: `${year} 年`,
}));

const balColumns = ref<ColumnDef<LeaveBalance>[]>([
  { accessorKey: "employee_no", header: "工号", size: 100 },
  { accessorKey: "employee_name", header: "姓名", size: 100 },
  { id: "org", header: "部门", size: 110, cell: ({ row }) => orgNameOf(row.original.org_id) },
  {
    id: "leave_type",
    header: "假期类型",
    size: 110,
    cell: ({ row }) => row.original.leave_type_name ?? "--",
  },
  { accessorKey: "year", header: "年度", size: 80 },
  {
    id: "total_quota",
    header: "总额度",
    size: 90,
    cell: ({ row }) => `${row.original.total_quota}${unitTextById(row.original.leave_type_id)}`,
  },
  {
    id: "used",
    header: "已用",
    size: 90,
    cell: ({ row }) => `${row.original.used}${unitTextById(row.original.leave_type_id)}`,
  },
  {
    id: "frozen",
    header: "冻结",
    size: 90,
    cell: ({ row }) => `${row.original.frozen}${unitTextById(row.original.leave_type_id)}`,
  },
  {
    id: "balance",
    header: "可用余额",
    size: 100,
    cell: ({ row }) => `${row.original.balance}${unitTextById(row.original.leave_type_id)}`,
  },
  {
    id: "actions",
    header: "操作",
    size: 100,
    cell: ({ row }) => {
      const item = row.original;
      if (!canWrite.value) {
        return h("span", { class: "text-muted-foreground text-xs" }, "--");
      }
      return h(
        Button,
        {
          variant: "ghost",
          size: "sm",
          "data-testid": `leave-balance-adjust-${item.id}`,
          onClick: () => openBalanceAdjust(item),
        },
        () => "调整"
      );
    },
  },
] as ColumnDef<LeaveBalance>[]);

function unitTextById(leaveTypeId: string): string {
  return unitText(leaveTypes.value.find((t) => t.id === leaveTypeId));
}

const balDataTable = useDataTable<LeaveBalance>({
  columns: balColumns.value,
  enabled: () => activeTab.value === "balances",
  remoteFetchFn: async ({ page, page_size }) => {
    const query: LeaveBalanceQuery = {
      page,
      page_size,
      year: Number(balYear.value),
      leave_type_id: balTypeId.value === ALL ? undefined : balTypeId.value,
      org_id: balOrgIds.value[0] || undefined,
      keyword: balKeyword.value || undefined,
    };
    const res = await listLeaveBalances(query);
    return envelope<LeaveBalance>(res, page, page_size);
  },
});

function handleBalSearch() {
  balDataTable.refresh(true);
}

function handleBalReset() {
  balYear.value = String(currentYear);
  balTypeId.value = ALL;
  balOrgIds.value = [];
  balKeyword.value = "";
  balDataTable.refresh(true);
}

const adjustOpen = ref(false);
const adjustTarget = ref<LeaveBalance | null>(null);

function openBalanceAdjust(item: LeaveBalance) {
  adjustTarget.value = item;
  adjustOpen.value = true;
}

/* ── 初始化 ── */

onMounted(() => {
  void loadLeaveTypes();
  void getOrgTree()
    .then((res) => {
      orgTree.value = res.data ?? [];
    })
    .catch(() => {
      orgTree.value = [];
    });
});
</script>

<template>
  <AppPage
    title="假勤管理"
    description="假期类型字典、请假单审批与假期余额调整的统一入口；请假通过后自动写入考勤记录"
  >
    <Tabs v-model="activeTab" default-value="types" class="flex h-full min-h-0 flex-col gap-4">
      <TabsList data-testid="leave-tabs">
        <TabsTrigger value="types" data-testid="leave-tab-types">假期类型</TabsTrigger>
        <TabsTrigger value="requests" data-testid="leave-tab-requests">请假单</TabsTrigger>
        <TabsTrigger value="balances" data-testid="leave-tab-balances">假期余额</TabsTrigger>
      </TabsList>

      <!-- 页签一：假期类型 -->
      <TabsContent value="types" class="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div class="ring-foreground/10 bg-card flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
          <div class="flex shrink-0 items-center justify-between gap-2 border-b px-5 py-3">
            <div class="text-xs font-medium">假期类型</div>
            <Button
              v-if="canWrite"
              size="sm"
              data-testid="open-leave-type-form"
              @click="openTypeForm(null)"
            >
              新增类型
            </Button>
          </div>
          <div class="flex min-h-0 flex-1 flex-col px-5 pt-4">
            <DataTable :data-table="typeDataTable" :fixed-layout="true" />
          </div>
        </div>
      </TabsContent>

      <!-- 页签二：请假单 -->
      <TabsContent value="requests" class="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div class="ring-foreground/10 bg-card flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
          <div class="flex shrink-0 flex-wrap items-center gap-2 border-b px-5 py-3">
            <Select
              v-model="reqStatus"
              trigger-class="w-32"
              :options="statusFilterOptions"
              data-testid="leave-req-status-filter"
            />
            <Select
              v-model="reqTypeId"
              trigger-class="w-36"
              :options="typeFilterOptions"
              data-testid="leave-req-type-filter"
            />
            <OrganizationSelect
              v-model="reqOrgIds"
              :multiple="false"
              placeholder="部门"
              class="w-44"
              data-testid="leave-req-org-filter"
            />
            <Input
              v-model="reqKeyword"
              class="w-40"
              placeholder="姓名/工号"
              data-testid="leave-req-keyword-input"
              @keyup.enter="handleReqSearch"
            />
            <DateInput v-model="reqDateFrom" placeholder="开始日期" class="w-40" data-testid="leave-req-date-from" />
            <DateInput v-model="reqDateTo" placeholder="结束日期" class="w-40" data-testid="leave-req-date-to" />
            <Button variant="outline" size="sm" data-testid="leave-req-search" @click="handleReqSearch">搜索</Button>
            <Button variant="ghost" size="sm" data-testid="leave-req-reset" @click="handleReqReset">重置</Button>
          </div>
          <div class="flex min-h-0 flex-1 flex-col px-5 pt-4">
            <DataTable :data-table="reqDataTable" :fixed-layout="true" />
          </div>
        </div>
      </TabsContent>

      <!-- 页签三：假期余额 -->
      <TabsContent value="balances" class="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div class="ring-foreground/10 bg-card flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
          <div class="flex shrink-0 flex-wrap items-center gap-2 border-b px-5 py-3">
            <Select
              v-model="balYear"
              trigger-class="w-32"
              :options="yearOptions"
              data-testid="leave-bal-year-filter"
            />
            <Select
              v-model="balTypeId"
              trigger-class="w-36"
              :options="typeFilterOptions"
              data-testid="leave-bal-type-filter"
            />
            <OrganizationSelect
              v-model="balOrgIds"
              :multiple="false"
              placeholder="部门"
              class="w-44"
              data-testid="leave-bal-org-filter"
            />
            <Input
              v-model="balKeyword"
              class="w-40"
              placeholder="姓名/工号"
              data-testid="leave-bal-keyword-input"
              @keyup.enter="handleBalSearch"
            />
            <Button variant="outline" size="sm" data-testid="leave-bal-search" @click="handleBalSearch">搜索</Button>
            <Button variant="ghost" size="sm" data-testid="leave-bal-reset" @click="handleBalReset">重置</Button>
          </div>
          <div class="flex min-h-0 flex-1 flex-col px-5 pt-4">
            <DataTable :data-table="balDataTable" :fixed-layout="true" />
          </div>
        </div>
      </TabsContent>
    </Tabs>

    <LeaveTypeFormModal v-model:open="typeFormOpen" :leave-type="typeFormTarget" @saved="refreshTypes" />
    <LeaveApproveModal v-model:open="approveOpen" :request="approveTarget" @saved="reqDataTable.refresh()" />
    <PeopleSelectDialog
      v-model:open="transferOpen"
      v-model="transferOwnerIds"
      :multiple="false"
      title="移交请假单"
      confirm-text="确认移交"
      @confirm="handleTransferConfirm"
    />
    <LeaveBalanceAdjustModal
      v-model:open="adjustOpen"
      :balance="adjustTarget"
      @saved="balDataTable.refresh()"
    />
  </AppPage>
</template>
