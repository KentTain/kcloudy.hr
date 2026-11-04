<script setup lang="ts">
/**
 * 薪酬项编辑弹窗：定义字段 + ext_data 规则元数据（计税/社保基数/月度固定/单位）。
 * 编码创建后不可修改（发薪明细按 code 关联历史数据），编辑态置灰。
 */
import { ref, watch } from "vue";

import { Button, Input, Select, Switch } from "@/components";
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

import { createSalaryItem, updateSalaryItem } from "@/hr/api/salary";
import type { SalaryItem, SalaryItemExtData } from "@/hr/types/salary";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  item: SalaryItem | null;
  categories: string[];
}>();

const emit = defineEmits<{ saved: [] }>();

const submitting = ref(false);
const code = ref("");
const name = ref("");
const category = ref("");
const taxable = ref(true);
const socialSecurityBase = ref(false);
const monthlyFixed = ref(false);
const unit = ref("元/月");
const sort = ref(0);

const categoryOptions = ref<{ value: string; label: string }[]>([]);

watch(
  open,
  (value) => {
    if (!value) return;
    // immediate：以 open=true 初始挂载（如测试或直开场景）也完成回填
    categoryOptions.value = props.categories.map((c) => ({ value: c, label: c }));
    if (props.item) {
      code.value = props.item.code;
      name.value = props.item.name;
      category.value = props.item.category;
      taxable.value = props.item.ext_data?.taxable ?? false;
      socialSecurityBase.value = props.item.ext_data?.social_security_base ?? false;
      monthlyFixed.value = props.item.ext_data?.monthly_fixed ?? false;
      unit.value = props.item.ext_data?.unit ?? "元/月";
      sort.value = props.item.sort;
    } else {
      code.value = "";
      name.value = "";
      category.value = props.categories[0] ?? "";
      taxable.value = true;
      socialSecurityBase.value = false;
      monthlyFixed.value = false;
      unit.value = "元/月";
      sort.value = 0;
    }
  },
  { immediate: true },
);

function buildExtData(): SalaryItemExtData {
  return {
    taxable: taxable.value,
    social_security_base: socialSecurityBase.value,
    monthly_fixed: monthlyFixed.value,
    unit: unit.value.trim() || undefined,
  };
}

async function handleSubmit() {
  if (!name.value.trim()) {
    notifyError(new Error("请填写薪酬项名称"));
    return;
  }
  submitting.value = true;
  try {
    if (props.item) {
      await updateSalaryItem(props.item.id, {
        name: name.value.trim(),
        category: category.value,
        ext_data: buildExtData(),
        sort: sort.value,
      });
      notifySuccess("薪酬项已更新");
    } else {
      if (!code.value.trim()) {
        notifyError(new Error("请填写薪酬项编码"));
        submitting.value = false;
        return;
      }
      await createSalaryItem({
        code: code.value.trim(),
        name: name.value.trim(),
        category: category.value,
        ext_data: buildExtData(),
        sort: sort.value,
      });
      notifySuccess("薪酬项已创建");
    }
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "薪酬项保存失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-md" data-testid="salary-item-form-dialog">
      <DialogHeader>
        <DialogTitle>{{ props.item ? "编辑薪酬项" : "新增薪酬项" }}</DialogTitle>
        <DialogDescription>
          薪酬项为 EAV 字典定义，不承载金额；规则元数据影响定薪带出与发薪试算。
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4">
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-1.5">
            <Label>编码 *</Label>
            <Input
              v-model="code"
              :disabled="!!props.item"
              placeholder="如 base_monthly"
              data-testid="salary-item-code-input"
            />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>名称 *</Label>
            <Input v-model="name" placeholder="如 月度基本工资" data-testid="salary-item-name-input" />
          </div>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>类别</Label>
          <Select v-model="category" :options="categoryOptions" data-testid="salary-item-category-select" />
        </div>
        <div class="flex items-center gap-6">
          <span class="flex items-center gap-2">
            <Switch v-model="taxable" data-testid="salary-item-taxable" />
            <Label>计税</Label>
          </span>
          <span class="flex items-center gap-2">
            <Switch v-model="socialSecurityBase" data-testid="salary-item-social-base" />
            <Label>计入社保基数</Label>
          </span>
          <span class="flex items-center gap-2">
            <Switch v-model="monthlyFixed" data-testid="salary-item-monthly-fixed" />
            <Label>月度固定项</Label>
          </span>
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-1.5">
            <Label>单位</Label>
            <Input v-model="unit" placeholder="元/月" data-testid="salary-item-unit-input" />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>排序</Label>
            <Input
              :model-value="String(sort)"
              type="number"
              data-testid="salary-item-sort-input"
              @update:model-value="(v: string) => (sort = Number(v) || 0)"
            />
          </div>
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="salary-item-submit" @click="handleSubmit">
          {{ submitting ? "保存中…" : "保存" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
