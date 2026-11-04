<script setup lang="ts">
/**
 * 审批请求详情弹窗：摘要 + 变更明细（profile_change）+ 审批流水留痕，只读。
 */
import { computed, ref, watch } from "vue";

import { Badge, Button } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components";
import { DescriptionList } from "@/components";

import { getErrorMessage, notifyError } from "@/framework/utils/feedback";

import { getApprovalRequest } from "@/hr/api/approval";
import {
  APPROVAL_ACTION_LABELS,
  APPROVAL_BIZ_TYPE_LABELS,
  APPROVAL_STATUS_LABELS,
  APPROVAL_STATUS_VARIANTS,
  type ApprovalRequestDetail,
  type ProfileChangeEntry,
} from "@/hr/types/approval";
import type { FieldDefinition } from "@/hr/types/employee";
import { listFieldDefinitions } from "@/hr/api/field";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  requestId: string | null;
}>();

const emit = defineEmits<{ approve: [] }>();

const detail = ref<ApprovalRequestDetail | null>(null);
const definitions = ref<FieldDefinition[]>([]);

const items = computed(() => {
  const d = detail.value;
  if (!d) return [];
  return [
    { label: "单据标题", value: d.title },
    { label: "业务类型", value: APPROVAL_BIZ_TYPE_LABELS[d.biz_type] ?? d.biz_type },
    {
      label: "申请人",
      value: d.employee_name ? `${d.employee_name}（${d.employee_no ?? "—"}）` : "—",
    },
    { label: "当前状态", value: APPROVAL_STATUS_LABELS[d.status] },
    { label: "审批意见", value: d.approve_comment || "—" },
    { label: "提交时间", value: d.created_at?.replace("T", " ") ?? "—" },
  ];
});

const changes = computed<ProfileChangeEntry[]>(() => {
  const payload = detail.value?.payload;
  if (!payload || typeof payload !== "object") return [];
  const list = (payload as { changes?: unknown }).changes;
  return Array.isArray(list) ? (list as ProfileChangeEntry[]) : [];
});

function definitionNameOf(definitionId: string): string {
  return definitions.value.find((d) => d.id === definitionId)?.name ?? definitionId;
}

watch(
  [open, () => props.requestId],
  async ([value, id]) => {
    if (!value || !id) return;
    detail.value = null;
    try {
      const res = await getApprovalRequest(id);
      detail.value = res.data ?? null;
    } catch (error) {
      notifyError(error, getErrorMessage(error, "审批请求详情加载失败"));
    }
    if (changes.value.length > 0 && definitions.value.length === 0) {
      try {
        const res = await listFieldDefinitions();
        definitions.value = res.data ?? [];
      } catch {
        definitions.value = [];
      }
    }
  },
  { immediate: true },
);
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-xl" data-testid="approval-detail-dialog">
      <DialogHeader>
        <DialogTitle>审批详情</DialogTitle>
        <DialogDescription>审批请求摘要、业务载荷与流水留痕（只读）。</DialogDescription>
      </DialogHeader>
      <div v-if="detail" class="flex flex-col gap-4">
        <div class="flex items-center justify-between gap-2">
          <DescriptionList :items="items" :columns="2" data-testid="approval-detail-summary" />
        </div>
        <Badge :variant="APPROVAL_STATUS_VARIANTS[detail.status]" data-testid="approval-detail-status">
          {{ APPROVAL_STATUS_LABELS[detail.status] }}
        </Badge>

        <div v-if="changes.length > 0" class="flex flex-col gap-2">
          <div class="text-xs font-medium">变更明细</div>
          <div class="rounded-lg border text-sm">
            <div class="grid grid-cols-[1fr_1.4fr] gap-2 border-b px-3 py-2 text-xs text-muted-foreground">
              <div>属性</div>
              <div>新值</div>
            </div>
            <div
              v-for="(entry, index) in changes"
              :key="index"
              class="grid grid-cols-[1fr_1.4fr] gap-2 border-b px-3 py-2 last:border-b-0"
              :data-testid="`approval-detail-change-${index}`"
            >
              <div>{{ definitionNameOf(entry.definition_id) }}</div>
              <div class="break-all">{{ entry.new_value === null || entry.new_value === "" ? "（清空）" : String(entry.new_value) }}</div>
            </div>
          </div>
        </div>

        <div class="flex flex-col gap-2">
          <div class="text-xs font-medium">审批流水</div>
          <div
            v-if="detail.actions.length === 0"
            class="text-xs text-muted-foreground"
            data-testid="approval-detail-actions-empty"
          >
            暂无流水
          </div>
          <div v-else class="flex flex-col gap-1.5" data-testid="approval-detail-actions">
            <div
              v-for="action in detail.actions"
              :key="action.id"
              class="flex items-start gap-2 rounded-md border px-3 py-2 text-xs"
            >
              <Badge variant="secondary">{{ APPROVAL_ACTION_LABELS[action.action] ?? action.action }}</Badge>
              <div class="flex min-w-0 flex-1 flex-col gap-0.5">
                <div class="text-muted-foreground">
                  {{ action.actor_id ?? "—" }} · {{ action.created_at?.replace("T", " ") ?? "—" }}
                </div>
                <div v-if="action.comment" class="break-all">{{ action.comment }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <DialogFooter>
        <Button
          v-if="detail?.status === 'pending'"
          data-testid="approval-detail-to-approve"
          @click="emit('approve')"
        >
          去审批
        </Button>
        <Button variant="outline" @click="open = false">关闭</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
