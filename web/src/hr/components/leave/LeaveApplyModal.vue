<script setup lang="ts">
/**
 * 请假申请弹窗（console 我的假期）：选择启用的假期类型 + 起止时间，
 * 时长系统按类型单位计算（只读回显），事由必填。提交后进入待审批并冻结额度。
 */
import { computed, ref, watch } from "vue";

import { Button, Input, Label, Select, Textarea } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { submitMyLeaveRequest } from "@/hr/api/leave";
import { computeLeaveDuration, type LeaveType } from "@/hr/types/leave";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  /** 可选假期类型清单（仅启用类型） */
  leaveTypes: LeaveType[];
}>();

const emit = defineEmits<{ saved: [] }>();

const submitting = ref(false);
const leaveTypeId = ref("");
const startTime = ref("");
const endTime = ref("");
const reason = ref("");

const typeOptions = computed(() =>
  props.leaveTypes.map((t) => ({ value: t.id, label: `${t.name}（${t.unit === "day" ? "按天" : "按小时"}）` })),
);

const selectedType = computed(() => props.leaveTypes.find((t) => t.id === leaveTypeId.value) ?? null);

const duration = computed(() => {
  const t = selectedType.value;
  if (!t || !startTime.value || !endTime.value) return null;
  return computeLeaveDuration(t.unit, startTime.value, endTime.value);
});

const durationText = computed(() => {
  if (duration.value == null) return "—";
  return `${duration.value}${selectedType.value?.unit === "hour" ? "小时" : "天"}`;
});

watch(open, (value) => {
  if (!value) return;
  leaveTypeId.value = "";
  startTime.value = "";
  endTime.value = "";
  reason.value = "";
});

async function handleSubmit() {
  if (!leaveTypeId.value) {
    notifyError(new Error("请选择假期类型"));
    return;
  }
  if (!startTime.value || !endTime.value) {
    notifyError(new Error("请填写请假起止时间"));
    return;
  }
  if (duration.value == null || duration.value <= 0) {
    notifyError(new Error("结束时间须不早于开始时间"));
    return;
  }
  if (!reason.value.trim()) {
    notifyError(new Error("请填写请假事由"));
    return;
  }
  submitting.value = true;
  try {
    await submitMyLeaveRequest({
      leave_type_id: leaveTypeId.value,
      start_time: startTime.value,
      end_time: endTime.value,
      reason: reason.value.trim(),
    });
    notifySuccess("请假申请已提交，等待审批");
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "请假申请提交失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-md" data-testid="leave-apply-dialog">
      <DialogHeader>
        <DialogTitle>发起请假</DialogTitle>
        <DialogDescription>
          提交后额度先行冻结，审批通过转为已用并自动写入考勤；驳回或撤销后释放冻结。
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4">
        <div class="flex flex-col gap-1.5">
          <Label>假期类型 *</Label>
          <Select
            v-model="leaveTypeId"
            :options="typeOptions"
            placeholder="请选择假期类型"
            data-testid="leave-apply-type-select"
          />
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-1.5">
            <Label>开始时间 *</Label>
            <Input
              v-model="startTime"
              type="datetime-local"
              data-testid="leave-apply-start-input"
            />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>结束时间 *</Label>
            <Input v-model="endTime" type="datetime-local" data-testid="leave-apply-end-input" />
          </div>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>时长（系统计算）</Label>
          <Input
            :model-value="durationText"
            readonly
            data-testid="leave-apply-duration"
          />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>请假事由 *</Label>
          <Textarea
            v-model="reason"
            :rows="3"
            placeholder="请填写请假事由"
            data-testid="leave-apply-reason"
          />
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="leave-apply-submit" @click="handleSubmit">
          {{ submitting ? "提交中…" : "提交申请" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
