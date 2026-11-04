<script setup lang="ts">
/**
 * 请假单审批弹窗：只读摘要 + 审批意见，Footer 承载「通过 / 驳回」两动作；
 * 驳回时审批意见必填（驳回原因回写审批记录）。
 */
import { computed, ref, watch } from "vue";

import { Badge, Button, Label, Textarea } from "@/components";
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

import { approveLeaveRequest, rejectLeaveRequest } from "@/hr/api/leave";
import {
  LEAVE_REQUEST_STATUS_LABELS,
  LEAVE_UNIT_LABELS,
  type LeaveRequest,
} from "@/hr/types/leave";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  request: LeaveRequest | null;
}>();

const emit = defineEmits<{ saved: [] }>();

const submitting = ref(false);
const comment = ref("");

const items = computed(() => {
  const req = props.request;
  if (!req) return [];
  return [
    { label: "员工", value: req.employee_name ? `${req.employee_name}（${req.employee_no ?? "—"}）` : "—" },
    { label: "假期类型", value: req.leave_type_name ?? "—" },
    {
      label: "起止",
      value: `${req.start_time.replace("T", " ")} ~ ${req.end_time.replace("T", " ")}`,
    },
    {
      label: "时长",
      value: `${req.duration}${req.unit ? LEAVE_UNIT_LABELS[req.unit] ?? "" : ""}`,
    },
    { label: "事由", value: req.reason || "—" },
    { label: "当前状态", value: LEAVE_REQUEST_STATUS_LABELS[req.status] },
  ];
});

watch(open, (value) => {
  if (!value) return;
  comment.value = "";
});

async function handleApprove() {
  if (!props.request) return;
  submitting.value = true;
  try {
    await approveLeaveRequest(props.request.id);
    notifySuccess("已通过");
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
    await rejectLeaveRequest(props.request.id, comment.value.trim());
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
    <DialogContent class="sm:max-w-lg" data-testid="leave-approve-dialog">
      <DialogHeader>
        <DialogTitle>请假审批</DialogTitle>
        <DialogDescription>
          通过后按请假区间释放冻结额度并写入考勤记录（来源「请假」）；驳回后释放冻结额度。
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4">
        <DescriptionList :items="items" :columns="2" data-testid="leave-approve-summary" />
        <div class="flex flex-col gap-1.5">
          <Label>审批意见{{ comment.trim() ? "" : "（驳回时必填）" }}</Label>
          <Textarea
            v-model="comment"
            :rows="3"
            placeholder="如：项目排期冲突，建议调整休假时间"
            data-testid="leave-approve-comment"
          />
        </div>
        <Badge
          v-if="props.request?.status !== 'pending'"
          variant="secondary"
          data-testid="leave-approve-non-pending"
        >
          当前状态非待审批，操作可能被拒绝
        </Badge>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button
          variant="destructive"
          :disabled="submitting"
          data-testid="leave-approve-reject"
          @click="handleReject"
        >
          驳回
        </Button>
        <Button :disabled="submitting" data-testid="leave-approve-approve" @click="handleApprove">
          通过
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
