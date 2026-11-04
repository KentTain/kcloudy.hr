<script setup lang="ts">
/**
 * 新建/编辑考核周期弹窗（编辑仅 draft：周期名租户唯一、起止日期序校验后端兜底）
 */
import { ref, watch } from "vue";

import { Button, DateInput, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Input, Label } from "@/components";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { createPerfCycle, updatePerfCycle } from "@/hr/api/perf";
import type { PerfCycleItem } from "@/hr/types/perf";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  /** 编辑目标（null=新建） */
  cycle: PerfCycleItem | null;
}>();

const emit = defineEmits<{ saved: [] }>();

const name = ref("");
const startDate = ref("");
const endDate = ref("");
const submitting = ref(false);

watch(open, (value) => {
  if (!value) return;
  name.value = props.cycle?.name ?? "";
  startDate.value = props.cycle?.start_date ?? "";
  endDate.value = props.cycle?.end_date ?? "";
});

function validate(): string | null {
  if (!name.value.trim()) return "请填写周期名";
  if (!startDate.value) return "请选择起始日期";
  if (!endDate.value) return "请选择截止日期";
  if (endDate.value < startDate.value) return "截止日期须不早于起始日期";
  return null;
}

async function handleSubmit() {
  const message = validate();
  if (message) {
    notifyError(new Error(message), message);
    return;
  }
  submitting.value = true;
  try {
    if (props.cycle) {
      await updatePerfCycle(props.cycle.id, {
        name: name.value.trim(),
        start_date: startDate.value,
        end_date: endDate.value,
      });
      notifySuccess("周期已更新");
    } else {
      await createPerfCycle({
        name: name.value.trim(),
        start_date: startDate.value,
        end_date: endDate.value,
      });
      notifySuccess("周期已创建");
    }
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "保存失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-md" data-testid="perf-cycle-form-modal">
      <DialogHeader>
        <DialogTitle>{{ cycle ? "编辑周期" : "新建周期" }}</DialogTitle>
        <DialogDescription>
          周期名租户内唯一；创建后为草稿态，激活前可随时编辑或删除
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4 py-2">
        <div class="flex flex-col gap-2">
          <Label for="cycle-name">周期名</Label>
          <Input
            id="cycle-name"
            v-model="name"
            placeholder="如 2026-H1"
            data-testid="cycle-name-input"
          />
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-2">
            <Label>起始日期</Label>
            <DateInput v-model="startDate" data-testid="cycle-start-input" />
          </div>
          <div class="flex flex-col gap-2">
            <Label>截止日期</Label>
            <DateInput v-model="endDate" data-testid="cycle-end-input" />
          </div>
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" data-testid="cycle-form-cancel" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="cycle-form-submit" @click="handleSubmit">
          {{ cycle ? "保存" : "创建" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
