<script setup lang="ts">
/**
 * 审批管理页：审批请求列表（池模式审批，具备 hr:approval:approve 权限者处理）。
 * 行操作：详情（摘要+流水只读）/ 审批（待审批且具备权限）；请假单审批仍在假勤管理，
 * 本页为统一审批流（当前 biz_type=profile_change，预留 leave 等）。
 */
import type { ColumnDef } from "@tanstack/vue-table";
import { computed, h, ref } from "vue";

import {
  Badge,
  Button,
  DataTable,
  Input,
  PeopleSelectDialog,
  Select,
  useDataTable,
} from "@/components";
import AppPage from "@/framework/layouts/components/AppPage.vue";

import { useUserStore } from "@/framework/stores";
import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { listApprovalRequests, transferApprovalRequest } from "@/hr/api/approval";
import ApprovalActionModal from "@/hr/components/approval/ApprovalActionModal.vue";
import ApprovalDetailDialog from "@/hr/components/approval/ApprovalDetailDialog.vue";
import {
  APPROVAL_BIZ_TYPE_LABELS,
  APPROVAL_STATUS_LABELS,
  APPROVAL_STATUS_VARIANTS,
  type ApprovalBizType,
  type ApprovalRequestItem,
  type ApprovalRequestQuery,
  type ApprovalStatus,
} from "@/hr/types/approval";

const userStore = useUserStore();
const canApprove = computed(() => userStore.hasPermission("hr:approval:approve"));
const canTransfer = computed(() => userStore.hasPermission("hr:approval:transfer"));

const ALL = "__all__";

const bizType = ref<ApprovalBizType | typeof ALL>(ALL);
const status = ref<ApprovalStatus | typeof ALL>(ALL);
const keyword = ref("");

const bizTypeOptions = [
  { value: ALL, label: "全部业务类型" },
  ...(Object.keys(APPROVAL_BIZ_TYPE_LABELS) as ApprovalBizType[]).map((value) => ({
    value,
    label: APPROVAL_BIZ_TYPE_LABELS[value],
  })),
];
const statusOptions = [
  { value: ALL, label: "全部状态" },
  ...(Object.keys(APPROVAL_STATUS_LABELS) as ApprovalStatus[]).map((value) => ({
    value,
    label: APPROVAL_STATUS_LABELS[value],
  })),
];

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

const columns = ref<ColumnDef<ApprovalRequestItem>[]>([
  { accessorKey: "employee_no", header: "工号", size: 100 },
  { accessorKey: "employee_name", header: "姓名", size: 100 },
  { accessorKey: "title", header: "单据标题", size: 200 },
  {
    accessorKey: "biz_type",
    header: "业务类型",
    size: 120,
    cell: ({ row }) => APPROVAL_BIZ_TYPE_LABELS[row.original.biz_type] ?? row.original.biz_type,
  },
  {
    accessorKey: "status",
    header: "状态",
    size: 90,
    cell: ({ row }) =>
      h(
        Badge,
        { variant: APPROVAL_STATUS_VARIANTS[row.original.status] },
        () => APPROVAL_STATUS_LABELS[row.original.status]
      ),
  },
  {
    accessorKey: "created_at",
    header: "提交时间",
    size: 160,
    cell: ({ row }) => row.original.created_at?.replace("T", " ") ?? "--",
  },
  {
    id: "actions",
    header: "操作",
    size: 180,
    cell: ({ row }) => {
      const item = row.original;
      const buttons = [] as ReturnType<typeof h>[];
      buttons.push(
        h(
          Button,
          {
            variant: "ghost",
            size: "sm",
            "data-testid": `approval-detail-${item.id}`,
            onClick: () => openDetail(item),
          },
          () => "详情"
        )
      );
      if (item.status === "pending" && canApprove.value) {
        buttons.push(
          h(
            Button,
            {
              variant: "ghost",
              size: "sm",
              "data-testid": `approval-approve-${item.id}`,
              onClick: () => openAction(item),
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
              "data-testid": `approval-transfer-${item.id}`,
              onClick: () => openTransfer(item),
            },
            () => "移交"
          )
        );
      }
      return h("div", { class: "flex items-center gap-1" }, buttons);
    },
  },
] as ColumnDef<ApprovalRequestItem>[]);

const dataTable = useDataTable<ApprovalRequestItem>({
  columns: columns.value,
  remoteFetchFn: async ({ page, page_size }) => {
    const query: ApprovalRequestQuery = {
      page,
      page_size,
      biz_type: bizType.value === ALL ? undefined : bizType.value,
      status: status.value === ALL ? undefined : status.value,
      keyword: keyword.value || undefined,
    };
    try {
      const res = await listApprovalRequests(query);
      return envelope<ApprovalRequestItem>(res, page, page_size);
    } catch (error) {
      notifyError(error, getErrorMessage(error, "审批请求加载失败"));
      throw error;
    }
  },
});

function handleSearch() {
  dataTable.refresh(true);
}

function handleReset() {
  bizType.value = ALL;
  status.value = ALL;
  keyword.value = "";
  dataTable.refresh(true);
}

/* ── 详情 / 审批弹窗 ── */

const detailOpen = ref(false);
const detailId = ref<string | null>(null);
const detailRow = ref<ApprovalRequestItem | null>(null);

function openDetail(item: ApprovalRequestItem) {
  detailId.value = item.id;
  detailRow.value = item;
  detailOpen.value = true;
}

function detailToApprove() {
  detailOpen.value = false;
  if (detailRow.value) openAction(detailRow.value);
}

const actionOpen = ref(false);
const actionTarget = ref<ApprovalRequestItem | null>(null);

function openAction(item: ApprovalRequestItem) {
  actionTarget.value = item;
  actionOpen.value = true;
}

/* ── 审批请求移交（数据归属 D2） ── */

const transferOpen = ref(false);
const transferTarget = ref<ApprovalRequestItem | null>(null);
const transferOwnerIds = ref<string[]>([]);

function openTransfer(item: ApprovalRequestItem) {
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
    await transferApprovalRequest(target.id, userIds[0]);
    const targetName = users[0]?.nickname || users[0]?.username;
    notifySuccess(targetName ? `已移交至 ${targetName}` : "移交成功");
    dataTable.refresh();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "移交失败"));
  }
}
</script>

<template>
  <AppPage
    title="审批管理"
    description="统一审批流处理入口；通过后系统应用业务变更，驳回须填写审批意见，全过程流水留痕"
  >
    <div class="ring-foreground/10 bg-card flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
      <div class="flex shrink-0 flex-wrap items-center gap-2 border-b px-5 py-3">
        <Select
          v-model="bizType"
          trigger-class="w-36"
          :options="bizTypeOptions"
          data-testid="approval-biz-type-filter"
        />
        <Select
          v-model="status"
          trigger-class="w-32"
          :options="statusOptions"
          data-testid="approval-status-filter"
        />
        <Input
          v-model="keyword"
          class="w-40"
          placeholder="姓名/工号"
          data-testid="approval-keyword-input"
          @keyup.enter="handleSearch"
        />
        <Button variant="outline" size="sm" data-testid="approval-search" @click="handleSearch">搜索</Button>
        <Button variant="ghost" size="sm" data-testid="approval-reset" @click="handleReset">重置</Button>
      </div>
      <div class="flex min-h-0 flex-1 flex-col px-5 pt-4">
        <DataTable :data-table="dataTable" :fixed-layout="true" />
      </div>
    </div>

    <ApprovalDetailDialog
      v-model:open="detailOpen"
      :request-id="detailId"
      @approve="detailToApprove"
    />
    <ApprovalActionModal v-model:open="actionOpen" :request="actionTarget" @saved="dataTable.refresh()" />
    <PeopleSelectDialog
      v-model:open="transferOpen"
      v-model="transferOwnerIds"
      :multiple="false"
      title="移交审批请求"
      confirm-text="确认移交"
      @confirm="handleTransferConfirm"
    />
  </AppPage>
</template>
