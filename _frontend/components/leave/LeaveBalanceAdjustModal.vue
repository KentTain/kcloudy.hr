<script setup lang="ts">
/**
 * 假期余额调整弹窗：调整指定员工×类型×年度的总额度（total_quota）。
 * 已用/冻结只读展示；可用余额 = 总额度 - 已用 - 冻结。
 */
import { computed, ref, watch } from "vue";

import { Button, Input, Label } from "@/components";
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

import { adjustLeaveBalance } from "@/hr/api/leave";
import { LEAVE_UNIT_LABELS, type LeaveBalance } from "@/hr/types/leave";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  balance: LeaveBalance | null;
}>();

const emit = defineEmits<{ saved: [] }>();

const submitting = ref(false);
const totalQuota = ref(0);

const items = computed(() => {
  const b = props.balance;
  if (!b) return [];
  const unitSuffix = b.unit ? LEAVE_UNIT_LABELS[b.unit] ?? "" : "";
  return [
    { label: "员工", value: b.employee_name ? `${b.employee_name}（${b.employee_no ?? "—"}）` : "—" },
    { label: "假期类型", value: b.leave_type_name ?? "—" },
    { label: "年度", value: String(b.year) },
    { label: "已用", value: `${b.used}${unitSuffix}` },
    { label: "冻结", value: `${b.frozen}${unitSuffix}` },
    {
      label: "当前可用",
      value: `${b.balance}${unitSuffix}`,
    },
  ];
});

watch(
  open,
  (value) => {
    if (!value) return;
    totalQuota.value = props.balance?.total_quota ?? 0;
  },
  { immediate: true },
);

async function handleSubmit() {
  if (!props.balance) return;
  submitting.value = true;
  try {
    await adjustLeaveBalance(props.balance.id, totalQuota.value);
    notifySuccess("假期余额已调整");
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "余额调整失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-md" data-testid="leave-balance-adjust-dialog">
      <DialogHeader>
        <DialogTitle>调整假期余额</DialogTitle>
        <DialogDescription>
          调整总额度后可用余额随之变化；已用与冻结额度由请假单流转自动维护，不可手工修改。
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4">
        <DescriptionList :items="items" :columns="2" data-testid="leave-balance-adjust-summary" />
        <div class="flex flex-col gap-1.5">
          <Label>新总额度 *</Label>
          <Input
            :model-value="String(totalQuota)"
            type="number"
            data-testid="leave-balance-adjust-quota-input"
            @update:model-value="(v: string) => (totalQuota = Number(v) || 0)"
          />
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button
          :disabled="submitting"
          data-testid="leave-balance-adjust-submit"
          @click="handleSubmit"
        >
          {{ submitting ? "保存中…" : "保存" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
