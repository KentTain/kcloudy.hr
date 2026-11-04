<script setup lang="ts">
/**
 * 定薪/调薪弹窗：薪酬项行编辑（可增删）+ 原因 + 生效日期 + 新旧方案对比。
 * 生效日后当期发薪按新旧区间分段折算；生效日期早于当日被拒绝。
 */
import { computed, ref, watch } from "vue";

import { Button, DateInput, Input, Select } from "@/components";
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

import { adjustSalaryPackage } from "@/hr/api/salary";
import { listSalaryItemOptions } from "@/hr/api/reference";
import { SALARY_PACKAGE_REASON_LABELS, type SalaryPackageItemInput } from "@/hr/types/salary";
import type { SalaryItemOption, SalaryPackageRecord } from "@/hr/types/employee";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  employeeId: string;
  employeeName: string;
  /** 当前生效方案行（调薪对比基准） */
  currentPackages: SalaryPackageRecord[];
}>();

const emit = defineEmits<{ saved: [] }>();

const submitting = ref(false);
const reason = ref("adjust");
const effectiveFrom = ref("");
const rows = ref<SalaryPackageItemInput[]>([]);
const itemOptions = ref<SalaryItemOption[]>([]);

const REASON_OPTIONS = Object.entries(SALARY_PACKAGE_REASON_LABELS).map(([value, label]) => ({
  value,
  label,
}));

const itemSelectOptions = computed(() =>
  itemOptions.value.map((option) => ({
    value: option.id,
    label: `${option.name}（${option.code}）`,
  })),
);

/** 新旧对比：同 item 的旧金额（无旧行 = 新增项） */
function oldAmountOf(itemId: string): number | null {
  return props.currentPackages.find((row) => row.item_id === itemId)?.amount ?? null;
}

watch(open, async (value) => {
  if (!value) return;
  // immediate：以 open=true 初始挂载（如测试或直开场景）也完成回填
  reason.value = "adjust";
  const today = new Date();
  effectiveFrom.value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  rows.value = props.currentPackages.map((row) => ({ item_id: row.item_id, amount: row.amount }));
  try {
    const res = await listSalaryItemOptions();
    itemOptions.value = res.data ?? [];
  } catch {
    itemOptions.value = [];
  }
}, { immediate: true });

function addRow() {
  rows.value = [...rows.value, { item_id: "", amount: 0 }];
}

function removeRow(index: number) {
  rows.value = rows.value.filter((_, i) => i !== index);
}

async function handleSubmit() {
  if (!rows.value.length) {
    notifyError(new Error("请至少保留一行薪酬项"));
    return;
  }
  if (rows.value.some((row) => !row.item_id)) {
    notifyError(new Error("存在未选择薪酬项的行"));
    return;
  }
  if (rows.value.some((row) => !(row.amount > 0))) {
    notifyError(new Error("薪酬项金额需大于 0"));
    return;
  }
  if (!effectiveFrom.value) {
    notifyError(new Error("请选择生效日期"));
    return;
  }
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  if (effectiveFrom.value < todayStr) {
    notifyError(new Error("生效日期不能早于当日"));
    return;
  }
  submitting.value = true;
  try {
    await adjustSalaryPackage(props.employeeId, {
      items: rows.value.map((row) => ({ item_id: row.item_id, amount: Number(row.amount) })),
      reason: reason.value,
      effective_from: effectiveFrom.value,
    });
    notifySuccess(`「${props.employeeName}」薪酬方案已保存，生效后当期发薪分段折算`);
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "薪酬方案保存失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-xl" data-testid="salary-package-editor-dialog">
      <DialogHeader>
        <DialogTitle>发起调薪 · {{ props.employeeName }}</DialogTitle>
        <DialogDescription>按区间版本化保存：生效即闭合旧区间并生成新区间，异动流水同步留痕。</DialogDescription>
      </DialogHeader>

      <!-- 新旧方案对比 -->
      <div class="rounded-lg border p-3" data-testid="package-comparison">
        <div class="text-muted-foreground mb-2 text-xs font-medium">新旧方案对比</div>
        <div v-if="!props.currentPackages.length" class="text-muted-foreground text-xs">当前无生效方案，本次为首次定薪。</div>
        <div v-else class="flex flex-col gap-1 text-xs">
          <div v-for="row in props.currentPackages" :key="row.item_id" class="flex items-center justify-between gap-2">
            <span>{{ row.item_name ?? row.item_code }}</span>
            <span class="text-muted-foreground">
              {{ row.amount.toFixed(2) }} →
              <span class="text-foreground font-medium">
                {{ rows.find((r) => r.item_id === row.item_id)?.amount?.toFixed(2) ?? "移除" }}
              </span>
            </span>
          </div>
        </div>
      </div>

      <!-- 方案编辑行 -->
      <div class="flex flex-col gap-2">
        <div class="flex items-center justify-between">
          <Label>方案明细（元/月）</Label>
          <Button variant="outline" size="sm" data-testid="package-add-row" @click="addRow">添加行</Button>
        </div>
        <div v-for="(row, index) in rows" :key="index" class="flex items-center gap-2">
          <div class="min-w-0 flex-1">
            <Select
              :model-value="row.item_id"
                  :options="itemSelectOptions"
              :data-testid="`package-item-select-${index}`"
              @update:model-value="(v: string) => (rows[index] = { ...row, item_id: v })"
            />
          </div>
          <Input
            :model-value="String(row.amount)"
            type="number"
            class="w-32"
            :data-testid="`package-amount-input-${index}`"
            @update:model-value="(v: string) => (rows[index] = { ...row, amount: Number(v) || 0 })"
          />
          <Button variant="ghost" size="sm" :data-testid="`package-remove-row-${index}`" @click="removeRow(index)">
            删除
          </Button>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-4">
        <div class="flex flex-col gap-1.5">
          <Label>调薪原因</Label>
          <Select v-model="reason" :options="REASON_OPTIONS" data-testid="package-reason-select" />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>生效日期 *</Label>
          <DateInput v-model="effectiveFrom" data-testid="package-effective-from" />
        </div>
      </div>

      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="package-submit" @click="handleSubmit">
          {{ submitting ? "保存中…" : "保存方案" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
