<script setup lang="ts">
/**
 * 审批操作弹窗：只读摘要 + 变更明细 + 审批意见，Footer 承载「通过 / 驳回」；
 * 驳回时审批意见必填；通过时回调后端 handler 应用业务变更（失败整体回滚）。
 */
import { computed, ref, watch } from "vue";

import { Button, Label, Textarea } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components";
import { DescriptionList } from "@/components";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { approveApprovalRequest, rejectApprovalRequest } from "@/hr/api/approval";
import {
  APPROVAL_BIZ_TYPE_LABELS,
  type ApprovalRequestItem,
  type ProfileChangeEntry,
} from "@/hr/types/approval";
import type { FieldDefinition } from "@/hr/types/employee";
import { listFieldDefinitions } from "@/hr/api/field";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  request: ApprovalRequestItem | null;
}>();

const emit = defineEmits<{ saved: [] }>();

const submitting = ref(false);
const comment = ref("");
const definitions = ref<FieldDefinition[]>([]);

const items = computed(() => {
  const req = props.request;
  if (!req) return [];
  return [
    {
      label: "申请人",
      value: req.employee_name ? `${req.employee_name}（${req.employee_no ?? "—"}）` : "—",
    },
    { label: "单据标题", value: req.title },
    { label: "业务类型", value: APPROVAL_BIZ_TYPE_LABELS[req.biz_type] ?? req.biz_type },
    { label: "提交时间", value: req.created_at?.replace("T", " ") ?? "—" },
  ];
});

const changes = computed<ProfileChangeEntry[]>(() => {
  const payload = props.request?.payload;
  if (!payload || typeof payload !== "object") return [];
  const list = (payload as { changes?: unknown }).changes;
  return Array.isArray(list) ? (list as ProfileChangeEntry[]) : [];
});

function definitionNameOf(definitionId: string): string {
  return definitions.value.find((d) => d.id === definitionId)?.name ?? definitionId;
}

watch(open, async (value) => {
  if (!value) return;
  comment.value = "";
  if (changes.value.length > 0 && definitions.value.length === 0) {
    try {
      const res = await listFieldDefinitions();
      definitions.value = res.data ?? [];
    } catch {
      definitions.value = [];
    }
  }
});

async function handleApprove() {
  if (!props.request) return;
  submitting.value = true;
  try {
    await approveApprovalRequest(props.request.id, comment.value.trim() || undefined);
    notifySuccess("已通过，业务变更已应用");
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "审批操作失败"));
  } finally {
    submitting.value = false;
  }
}

async function handleReject() {
  if (!props.request) return;
  if (!comment.value.trim()) {
    notifyError(new Error("驳回时必须填写审批意见"));
    return;
  }
  submitting.value = true;
  try {
    await rejectApprovalRequest(props.request.id, comment.value.trim());
    notifySuccess("已驳回");
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "审批操作失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-lg" data-testid="approval-action-dialog">
      <DialogHeader>
        <DialogTitle>审批处理</DialogTitle>
        <DialogDescription>
          通过后系统应用业务变更（失败自动回滚保持待审批）；驳回须填写审批意见。
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4">
        <DescriptionList :items="items" :columns="2" data-testid="approval-action-summary" />

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
              :data-testid="`approval-action-change-${index}`"
            >
              <div>{{ definitionNameOf(entry.definition_id) }}</div>
              <div class="break-all">{{ entry.new_value === null || entry.new_value === "" ? "（清空）" : String(entry.new_value) }}</div>
            </div>
          </div>
        </div>

        <div class="flex flex-col gap-1.5">
          <Label>审批意见{{ comment.trim() ? "" : "（驳回时必填）" }}</Label>
          <Textarea
            v-model="comment"
            :rows="3"
            placeholder="如：材料核对无误，同意变更"
            data-testid="approval-action-comment"
          />
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button
          variant="destructive"
          :disabled="submitting"
          data-testid="approval-action-reject"
          @click="handleReject"
        >
          驳回
        </Button>
        <Button :disabled="submitting" data-testid="approval-action-approve" @click="handleApprove">
          通过
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
