<script setup lang="ts">
/**
 * 人事异动弹窗（转正/调岗/职级变更/调薪/离职；hire 由建档自动写入）
 */
import { computed, ref, watch } from "vue";

import { DateInput, Input, Select } from "@/components";
import { Button } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components";
import { Label } from "@/components";
import { OrganizationSelect } from "@/components";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { createChange } from "@/hr/api/employee";
import { getPositionOptions, listSalaryItemOptions } from "@/hr/api/reference";
import {
  CHANGE_TYPE_LABELS,
  MANUAL_CHANGE_TYPES,
  type ChangeType,
  type Employee,
  type PositionOption,
} from "@/hr/types/employee";

const open = defineModel<boolean>("open", { required: true });

const props = withDefaults(
  defineProps<{
    employee: Employee | null;
    /** 打开时预选的异动类型（如「办理离职」直达 offboard） */
    initialType?: ChangeType;
  }>(),
  { initialType: "probate" },
);

const emit = defineEmits<{ saved: [] }>();

const submitting = ref(false);
const changeType = ref<string>("probate");
const effectiveDate = ref<string>("");
const orgIds = ref<string[]>([]);
const positionId = ref<string>("");
const jobLevel = ref<string>("");
const reason = ref<string>("");
const remark = ref<string>("");
const salaryRows = ref<{ item_id: string; amount: number | null }[]>([]);
const positionOptions = ref<PositionOption[]>([]);
const salaryItemOptions = ref<{ id: string; name: string }[]>([]);

const changeTypeOptions = MANUAL_CHANGE_TYPES.map((value) => ({
  value,
  label: CHANGE_TYPE_LABELS[value],
}));

const isTransfer = computed(() => changeType.value === "transfer" || changeType.value === "level_change");
const isSalary = computed(() => changeType.value === "salary_change");
const isOffboard = computed(() => changeType.value === "offboard");

watch(open, async (value) => {
  if (!value) return;
  changeType.value = props.initialType;
  effectiveDate.value = new Date().toISOString().slice(0, 10);
  orgIds.value = props.employee?.org_id ? [props.employee.org_id] : [];
  positionId.value = props.employee?.position_id ?? "";
  jobLevel.value = props.employee?.job_level ?? "";
  reason.value = "";
  remark.value = "";
  salaryRows.value = [];
  // 岗位选项按员工当前组织拉取；薪酬项选项失败降级（无 hr:position:read / hr:salary_item:read 时仍可提交其余类型）
  if (props.employee?.org_id) {
    positionOptions.value = (await loadPositionOptions(props.employee.org_id)) ?? [];
  }
  if (!salaryItemOptions.value.length) {
    salaryItemOptions.value = (await loadSalaryItemOptions()) ?? [];
  }
}, { immediate: true });

async function loadPositionOptions(orgId: string): Promise<PositionOption[]> {
  try {
    const res = await getPositionOptions(orgId);
    return res.data ?? [];
  } catch {
    return [];
  }
}

async function loadSalaryItemOptions(): Promise<{ id: string; name: string }[]> {
  try {
    const res = await listSalaryItemOptions();
    return res.data ?? [];
  } catch {
    return [];
  }
}

function addSalaryRow() {
  salaryRows.value.push({ item_id: "", amount: null });
}

function removeSalaryRow(index: number) {
  salaryRows.value.splice(index, 1);
}

async function handleSubmit() {
  if (!props.employee) return;
  if (!effectiveDate.value) {
    notifyError(new Error("请选择生效日期"));
    return;
  }
  if (isSalary.value && salaryRows.value.some((row) => !row.item_id || row.amount == null)) {
    notifyError(new Error("请补全薪酬项与金额"));
    return;
  }
  submitting.value = true;
  try {
    await createChange({
      employee_id: props.employee.id,
      change_type: changeType.value as ChangeCreateType,
      effective_date: effectiveDate.value,
      ...(isTransfer.value ? { org_id: orgIds.value[0] || undefined, position_id: positionId.value || undefined, job_level: jobLevel.value || undefined } : {}),
      ...(isSalary.value
        ? {
            salary_items: salaryRows.value.map((row) => ({
              item_id: row.item_id,
              amount: Number(row.amount),
            })),
          }
        : {}),
      ...(isOffboard.value ? { reason: reason.value || undefined, remark: remark.value || undefined } : {}),
    });
    notifySuccess("异动已提交");
    emit("saved");
    open.value = false;
  } catch (error) {
    notifyError(error, getErrorMessage(error, "异动提交失败"));
  } finally {
    submitting.value = false;
  }
}

type ChangeCreateType = (typeof MANUAL_CHANGE_TYPES)[number];
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="sm:max-w-lg" data-testid="employee-change-modal">
      <DialogHeader>
        <DialogTitle>人事异动{{ employee ? ` - ${employee.name}` : "" }}</DialogTitle>
        <DialogDescription>转正/调岗/职级变更/调薪/离职，提交后按生效日期执行。</DialogDescription>
      </DialogHeader>

      <div class="flex flex-col gap-4 py-2">
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-1.5">
            <Label>异动类型</Label>
            <Select v-model="changeType" :options="changeTypeOptions" data-testid="change-type" />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>生效日期</Label>
            <DateInput v-model="effectiveDate" data-testid="change-effective-date" />
          </div>
        </div>

        <template v-if="isTransfer">
          <div class="flex flex-col gap-1.5">
            <Label>调入组织</Label>
            <OrganizationSelect v-model="orgIds" :multiple="false" placeholder="选择组织" />
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div class="flex flex-col gap-1.5">
              <Label>岗位</Label>
              <Select
                v-model="positionId"
                :options="positionOptions.map((p) => ({ value: p.id, label: p.name }))"
                placeholder="选择岗位"
              />
            </div>
            <div class="flex flex-col gap-1.5">
              <Label>职级</Label>
              <Input v-model="jobLevel" placeholder="如 P5" />
            </div>
          </div>
        </template>

        <template v-if="isSalary">
          <div class="flex flex-col gap-2">
            <div class="flex items-center justify-between">
              <Label>薪酬项调整</Label>
              <Button variant="outline" size="sm" @click="addSalaryRow">添加薪酬项</Button>
            </div>
            <div
              v-for="(row, index) in salaryRows"
              :key="index"
              class="grid grid-cols-[1fr_120px_32px] items-center gap-2"
              :data-testid="'salary-change-row'"
            >
              <Select
                v-model="row.item_id"
                :options="salaryItemOptions.map((item) => ({ value: item.id, label: item.name }))"
                placeholder="薪酬项"
              />
              <Input
                v-model.number="row.amount"
                type="number"
                placeholder="元/月"
              />
              <Button variant="ghost" size="sm" @click="removeSalaryRow(index)">删除</Button>
            </div>
            <p v-if="!salaryRows.length" class="text-muted-foreground text-xs">暂无调整行，点击「添加薪酬项」。</p>
          </div>
        </template>

        <template v-if="isOffboard">
          <div class="flex flex-col gap-1.5">
            <Label>离职原因</Label>
            <Input v-model="reason" placeholder="如 个人发展" />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>备注</Label>
            <Input v-model="remark" placeholder="选填" />
          </div>
        </template>
      </div>

      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="change-submit" @click="handleSubmit">
          提交异动
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
