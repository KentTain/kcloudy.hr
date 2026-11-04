<script setup lang="ts">
/**
 * 薪带表单弹窗：新建版本（可预填当前版本带宽）/ 编辑未生效版本。
 * 历史版本只读不入本弹窗；新建版本由后端自动闭合当前版本区间。
 */
import { ref, watch } from "vue";

import { Button, Input, DateInput } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components";
import { Label } from "@/components";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { createSalaryBand, updateSalaryBand } from "@/hr/api/salary";
import { bandEffectiveStatus, type SalaryBand } from "@/hr/types/salary";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  /** null=新建；传入行时按版本状态决定编辑（未生效）或新建版本（当前生效） */
  band: SalaryBand | null;
}>();

const emit = defineEmits<{ saved: [] }>();

const submitting = ref(false);
const jobLevel = ref("");
const minSalary = ref(0);
const midSalary = ref(0);
const maxSalary = ref(0);
const effectiveFrom = ref("");
const effectiveTo = ref("");

const isEdit = () => !!props.band && bandEffectiveStatus(props.band) === "upcoming";

watch(open, (value) => {
  if (!value) return;
  // immediate：以 open=true 初始挂载（如测试或直开场景）也完成回填
  if (props.band) {
    jobLevel.value = props.band.job_level;
    minSalary.value = props.band.min_salary;
    midSalary.value = props.band.mid_salary;
    maxSalary.value = props.band.max_salary;
    effectiveFrom.value = props.band.effective_from;
    effectiveTo.value = props.band.effective_to ?? "";
  } else {
    const today = new Date();
    jobLevel.value = "";
    minSalary.value = 0;
    midSalary.value = 0;
    maxSalary.value = 0;
    effectiveFrom.value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    effectiveTo.value = "";
  }
}, { immediate: true });

async function handleSubmit() {
  const min = Number(minSalary.value);
  const mid = Number(midSalary.value);
  const max = Number(maxSalary.value);
  if (!jobLevel.value.trim()) {
    notifyError(new Error("请填写职级"));
    return;
  }
  if (!(min <= mid && mid <= max)) {
    notifyError(new Error("带宽校验失败：需满足 下限 ≤ 中位值 ≤ 上限"));
    return;
  }
  if (!effectiveFrom.value) {
    notifyError(new Error("请选择生效起日期"));
    return;
  }
  submitting.value = true;
  try {
    if (isEdit()) {
      await updateSalaryBand(props.band!.id, {
        min_salary: min,
        mid_salary: mid,
        max_salary: max,
        effective_from: effectiveFrom.value,
        effective_to: effectiveTo.value || undefined,
      });
      notifySuccess("薪带已更新");
    } else {
      await createSalaryBand({
        job_level: jobLevel.value.trim(),
        min_salary: min,
        mid_salary: mid,
        max_salary: max,
        effective_from: effectiveFrom.value,
        effective_to: effectiveTo.value || undefined,
      });
      notifySuccess(props.band ? "薪带新版本已创建，原当前版本区间已自动闭合" : "薪带已创建");
    }
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "薪带保存失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-md" data-testid="band-form-dialog">
      <DialogHeader>
        <DialogTitle>
          {{ isEdit() ? "编辑薪带（未生效版本）" : props.band ? `新建「${props.band.job_level}」薪带版本` : "新建薪带" }}
        </DialogTitle>
        <DialogDescription>
          {{ isEdit()
            ? "仅未生效版本可编辑；历史版本只读。"
            : "新建版本自动闭合当前版本区间；同一职级任一时段仅一个生效版本。" }}
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4">
        <div class="flex flex-col gap-1.5">
          <Label>职级 *</Label>
          <Input
            v-model="jobLevel"
            :disabled="isEdit()"
            placeholder="如 P5 / M2"
            data-testid="band-job-level-input"
          />
        </div>
        <div class="grid grid-cols-3 gap-3">
          <div class="flex flex-col gap-1.5">
            <Label>下限（元/月）*</Label>
            <Input
              :model-value="String(minSalary)"
              type="number"
              data-testid="band-min-input"
              @update:model-value="(v: string) => (minSalary = Number(v) || 0)"
            />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>中位值（元/月）*</Label>
            <Input
              :model-value="String(midSalary)"
              type="number"
              data-testid="band-mid-input"
              @update:model-value="(v: string) => (midSalary = Number(v) || 0)"
            />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>上限（元/月）*</Label>
            <Input
              :model-value="String(maxSalary)"
              type="number"
              data-testid="band-max-input"
              @update:model-value="(v: string) => (maxSalary = Number(v) || 0)"
            />
          </div>
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-1.5">
            <Label>生效起 *</Label>
            <DateInput v-model="effectiveFrom" data-testid="band-effective-from" />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>生效止（空 = 当前版本）</Label>
            <DateInput v-model="effectiveTo" data-testid="band-effective-to" />
          </div>
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="band-submit" @click="handleSubmit">
          {{ submitting ? "保存中…" : "保存" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
