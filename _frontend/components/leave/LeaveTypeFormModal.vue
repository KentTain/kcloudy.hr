<script setup lang="ts">
/**
 * 假期类型编辑弹窗：编码创建后不可改（请假单/余额按类型关联历史数据）。
 * 额度规则 manual（仅手工调整）时默认额度不可填。
 */
import { ref, watch } from "vue";

import { Button, Input, Label, Select, Switch } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { createLeaveType, updateLeaveType } from "@/hr/api/leave";
import {
  LEAVE_QUOTA_RULE_LABELS,
  LEAVE_UNIT_LABELS,
  type LeaveType,
  type LeaveUnit,
} from "@/hr/types/leave";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  leaveType: LeaveType | null;
}>();

const emit = defineEmits<{ saved: [] }>();

const submitting = ref(false);
const code = ref("");
const name = ref("");
const unit = ref<LeaveUnit>("day");
const paid = ref(true);
const quotaRule = ref<"annual_fixed" | "manual">("annual_fixed");
const defaultQuota = ref(0);
const status = ref(true);

const unitOptions = (Object.keys(LEAVE_UNIT_LABELS) as LeaveUnit[]).map((value) => ({
  value,
  label: LEAVE_UNIT_LABELS[value],
}));
const quotaRuleOptions = (
  ["annual_fixed", "manual"] as const
).map((value) => ({ value, label: LEAVE_QUOTA_RULE_LABELS[value] }));

watch(
  open,
  (value) => {
    if (!value) return;
    if (props.leaveType) {
      code.value = props.leaveType.code;
      name.value = props.leaveType.name;
      unit.value = props.leaveType.unit;
      paid.value = props.leaveType.paid;
      quotaRule.value = props.leaveType.quota_rule;
      defaultQuota.value = props.leaveType.default_quota ?? 0;
      status.value = props.leaveType.status === "enabled";
    } else {
      code.value = "";
      name.value = "";
      unit.value = "day";
      paid.value = true;
      quotaRule.value = "annual_fixed";
      defaultQuota.value = 0;
      status.value = true;
    }
  },
  { immediate: true },
);

async function handleSubmit() {
  if (!name.value.trim()) {
    notifyError(new Error("请填写假期类型名称"));
    return;
  }
  submitting.value = true;
  try {
    if (props.leaveType) {
      await updateLeaveType(props.leaveType.id, {
        name: name.value.trim(),
        unit: unit.value,
        paid: paid.value,
        quota_rule: quotaRule.value,
        default_quota: quotaRule.value === "annual_fixed" ? defaultQuota.value : null,
        status: status.value ? "enabled" : "disabled",
      });
      notifySuccess("假期类型已更新");
    } else {
      if (!code.value.trim()) {
        notifyError(new Error("请填写假期类型编码"));
        submitting.value = false;
        return;
      }
      await createLeaveType({
        code: code.value.trim(),
        name: name.value.trim(),
        unit: unit.value,
        paid: paid.value,
        quota_rule: quotaRule.value,
        default_quota: quotaRule.value === "annual_fixed" ? defaultQuota.value : null,
      });
      notifySuccess("假期类型已创建");
    }
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "假期类型保存失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-md" data-testid="leave-type-form-dialog">
      <DialogHeader>
        <DialogTitle>{{ props.leaveType ? "编辑假期类型" : "新增假期类型" }}</DialogTitle>
        <DialogDescription>
          假期类型定义单位与额度规则；年度固定额度类型经「假期余额」页初始化与调整。
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4">
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-1.5">
            <Label>编码 *</Label>
            <Input
              v-model="code"
              :disabled="!!props.leaveType"
              placeholder="如 annual_leave"
              data-testid="leave-type-code-input"
            />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>名称 *</Label>
            <Input v-model="name" placeholder="如 年假" data-testid="leave-type-name-input" />
          </div>
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-1.5">
            <Label>单位</Label>
            <Select v-model="unit" :options="unitOptions" data-testid="leave-type-unit-select" />
          </div>
          <div class="flex items-center gap-2 pt-6">
            <Switch v-model="paid" data-testid="leave-type-paid-switch" />
            <Label>带薪</Label>
          </div>
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-1.5">
            <Label>额度规则</Label>
            <Select
              v-model="quotaRule"
              :options="quotaRuleOptions"
              data-testid="leave-type-quota-rule-select"
            />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>默认额度</Label>
            <Input
              :model-value="String(defaultQuota)"
              type="number"
              :disabled="quotaRule === 'manual'"
              :placeholder="quotaRule === 'manual' ? '手工调整' : '如 5'"
              data-testid="leave-type-default-quota-input"
              @update:model-value="(v: string) => (defaultQuota = Number(v) || 0)"
            />
          </div>
        </div>
        <div v-if="props.leaveType" class="flex items-center gap-2">
          <Switch v-model="status" data-testid="leave-type-status-switch" />
          <Label>{{ status ? "启用" : "停用" }}（停用后不可发起新请假）</Label>
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="leave-type-submit" @click="handleSubmit">
          {{ submitting ? "保存中…" : "保存" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
