<script setup lang="ts">
/**
 * 我的假期（console 员工自助，登录即可见，无权限码）：
 * 余额卡区（按启用假期类型展示总额度/已用/冻结/可用）+ 我的请假单
 * （状态筛选 + 列表 + 待审批可撤销）+ 发起请假弹窗。
 */
import type { ColumnDef } from "@tanstack/vue-table";
import { computed, h, onMounted, ref } from "vue";

import { Badge, Button, DataTable, Input, Select, useDataTable } from "@/components";
import AppPage from "@/framework/layouts/components/AppPage.vue";

import {
  confirmAction,
  getErrorMessage,
  notifyError,
  notifySuccess,
} from "@/framework/utils/feedback";

import {
  cancelMyLeaveRequest,
  listMyLeaveBalances,
  listMyLeaveRequests,
} from "@/hr/api/leave";
import LeaveApplyModal from "@/hr/components/leave/LeaveApplyModal.vue";
import {
  LEAVE_REQUEST_STATUS_LABELS,
  LEAVE_REQUEST_STATUS_VARIANTS,
  LEAVE_UNIT_LABELS,
  type LeaveBalance,
  type LeaveRequest,
  type LeaveRequestStatus,
  type LeaveType,
} from "@/hr/types/leave";

/* ── 余额卡区 ── */

const balances = ref<LeaveBalance[]>([]);
const balancesLoading = ref(false);

async function loadBalances() {
  balancesLoading.value = true;
  try {
    const res = await listMyLeaveBalances();
    balances.value = res.data ?? [];
  } catch (error) {
    notifyError(error, getErrorMessage(error, "假期余额加载失败"));
  } finally {
    balancesLoading.value = false;
  }
}

/** 申请弹窗可选类型：console 无类型清单端点，余额按启用类型全量下发，从余额派生 */
const applyTypes = computed<LeaveType[]>(() =>
  balances.value.map((b) => ({
    id: b.leave_type_id,
    code: b.leave_type_code ?? "",
    name: b.leave_type_name ?? "",
    unit: b.unit ?? "day",
    paid: true,
    quota_rule: "manual",
    default_quota: null,
    status: "enabled",
  })),
);

const balanceCards = computed(() =>
  balances.value.map((b) => ({
    id: b.id,
    name: b.leave_type_name ?? "--",
    unit: b.unit ? LEAVE_UNIT_LABELS[b.unit] ?? "" : "",
    total: b.total_quota,
    used: b.used,
    frozen: b.frozen,
    balance: b.balance,
  })),
);

/* ── 我的请假单 ── */

const statusFilter = ref<LeaveRequestStatus | "__all__">("__all__");

const statusOptions = (
  ["pending", "approved", "rejected", "cancelled"] as const
).map((value) => ({ value, label: LEAVE_REQUEST_STATUS_LABELS[value] }));
const statusFilterOptions = [{ value: "__all__", label: "全部状态" }, ...statusOptions];

const columns = ref<ColumnDef<LeaveRequest>[]>([
  {
    id: "leave_type",
    header: "假期类型",
    size: 110,
    cell: ({ row }) => row.original.leave_type_name ?? "--",
  },
  {
    id: "range",
    header: "起止时间",
    size: 250,
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
        () => LEAVE_REQUEST_STATUS_LABELS[row.original.status],
      ),
  },
  {
    id: "approve_comment",
    header: "审批意见",
    cell: ({ row }) => row.original.approve_comment || "--",
  },
  {
    id: "actions",
    header: "操作",
    size: 100,
    cell: ({ row }) => {
      const item = row.original;
      if (item.status !== "pending") {
        return h("span", { class: "text-muted-foreground text-xs" }, "--");
      }
      return h(
        Button,
        { variant: "ghost", size: "sm", "data-testid": `my-leave-cancel-${item.id}`, onClick: () => cancelRequest(item) },
        () => "撤销",
      );
    },
  },
] as ColumnDef<LeaveRequest>[]);

const dataTable = useDataTable<LeaveRequest>({
  columns: columns.value,
  remoteFetchFn: async ({ page, page_size }) => {
    const res = await listMyLeaveRequests({
      page,
      page_size,
      status: statusFilter.value === "__all__" ? undefined : statusFilter.value,
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

function handleSearch() {
  dataTable.refresh(true);
}

async function cancelRequest(item: LeaveRequest) {
  const confirmed = await confirmAction("确定撤销该请假申请？撤销后释放冻结额度，该单不可恢复。");
  if (!confirmed) return;
  try {
    await cancelMyLeaveRequest(item.id);
    notifySuccess("请假申请已撤销");
    dataTable.refresh();
    void loadBalances();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "撤销失败"));
  }
}

/* ── 发起请假 ── */

const applyOpen = ref(false);

function refreshAll() {
  dataTable.refresh();
  void loadBalances();
}

onMounted(() => {
  void loadBalances();
});
</script>

<template>
  <AppPage
    title="我的假期"
    description="查看各假期类型余额与自己的请假记录；请假提交后额度冻结，审批通过自动写入考勤"
  >
    <div class="flex h-full min-h-0 flex-col gap-4">
      <!-- 余额卡区 -->
      <div class="grid shrink-0 grid-cols-2 gap-4 md:grid-cols-4" data-testid="my-leave-balance-cards">
        <div
          v-for="card in balanceCards"
          :key="card.id"
          class="bg-card ring-foreground/10 rounded-xl p-4 text-sm ring-1 shadow-sm"
          :data-testid="`my-leave-balance-${card.id}`"
        >
          <p class="text-xs font-medium">{{ card.name }}</p>
          <p class="mt-1 text-2xl font-semibold">
            {{ card.balance }}<span class="text-muted-foreground ml-1 text-xs">{{ card.unit }}</span>
          </p>
          <p class="text-muted-foreground mt-1 text-xs">
            总额度 {{ card.total }}{{ card.unit }} · 已用 {{ card.used }}{{ card.unit }} · 冻结 {{ card.frozen }}{{ card.unit }}
          </p>
        </div>
        <div v-if="!balanceCards.length && !balancesLoading" class="bg-card ring-foreground/10 rounded-xl p-4 text-sm ring-1 shadow-sm">
          <p class="text-muted-foreground text-xs">暂无假期余额数据</p>
        </div>
      </div>

      <!-- 请假单列表 -->
      <div class="ring-foreground/10 bg-card flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
        <div class="flex shrink-0 items-center justify-between gap-2 border-b px-5 py-3">
          <div class="flex items-center gap-2">
            <div class="text-xs font-medium">我的请假单</div>
            <Select
              v-model="statusFilter"
              trigger-class="w-32"
              :options="statusFilterOptions"
              data-testid="my-leave-status-filter"
            />
            <Button variant="outline" size="sm" data-testid="my-leave-search" @click="handleSearch">查询</Button>
          </div>
          <Button size="sm" data-testid="open-leave-apply" @click="applyOpen = true">发起请假</Button>
        </div>
        <div class="flex min-h-0 flex-1 flex-col px-5 pt-4">
          <DataTable :data-table="dataTable" :fixed-layout="true" />
        </div>
      </div>
    </div>

    <LeaveApplyModal v-model:open="applyOpen" :leave-types="applyTypes" @saved="refreshAll" />
  </AppPage>
</template>
