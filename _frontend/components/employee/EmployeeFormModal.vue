<script setup lang="ts">
/**
 * 入职建档 / 员工编辑弹窗
 * - create：分步表单（基础信息 → 岗位任职 → 扩展属性），提交后自动生成工号并写 hire 流水；
 * - edit：单表单（同字段按模式裁剪，不含状态——状态由异动流转）。
 * 扩展属性经 json-render DynamicForm 渲染（values 以 definition_id 为键）。
 */
import { computed, ref, watch } from "vue";

import { Button } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components";
import { DateInput, Input, Select } from "@/components";
import { Label } from "@/components";
import { OrganizationSelect } from "@/components";
import { buildSettingFormSpec, type DynamicFormField } from "@/components";
import { JsonRender } from "@/components/json-render";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { createEmployee, updateEmployee } from "@/hr/api/employee";
import { listFieldDefinitions, listFieldGroups } from "@/hr/api/field";
import { getPositionOptions } from "@/hr/api/reference";
import type { Employee, EmployeeDetail, PositionOption } from "@/hr/types/employee";

const GENDER_OPTIONS = [
  { value: "male", label: "男" },
  { value: "female", label: "女" },
];

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  mode: "create" | "edit";
  employee?: EmployeeDetail | Employee | null;
}>();

const emit = defineEmits<{ saved: [employee: Employee] }>();

const submitting = ref(false);
const step = ref(0);
const name = ref("");
const gender = ref<string>("");
const birthDate = ref<string>("");
const idCard = ref<string>("");
const bankName = ref<string>("");
const phone = ref<string>("");
const workEmail = ref<string>("");
const orgIds = ref<string[]>([]);
const positionId = ref<string>("");
const jobLevel = ref<string>("");
const hireDate = ref<string>("");
const positionOptions = ref<PositionOption[]>([]);

// 扩展属性（create 模式第三步）
const attributeFormRef = ref<InstanceType<typeof JsonRender>>();
const attributeFields = ref<DynamicFormField[]>([]);
const attributeInitial = ref<Record<string, unknown>>({});
const EAV_CREATE_GROUP_CODES = ["basic", "work", "custom"];

const isEdit = computed(() => props.mode === "edit");
const stepTitles = isEdit.value ? ["员工信息"] : ["基础信息", "岗位任职", "扩展属性"];

const attributeBuild = computed(() => buildSettingFormSpec(attributeFields.value));

watch(open, async (value) => {
  if (!value) return;
  // immediate：以 open=true 初始挂载（如测试或直开场景）也完成回填
  step.value = 0;
  const employee = props.employee;
  const detail = (employee ?? null) as EmployeeDetail | null;
  name.value = employee?.name ?? "";
  gender.value = employee?.gender ?? "";
  birthDate.value = detail?.birth_date ?? "";
  idCard.value = detail?.id_card_masked ?? "";
  bankName.value = detail?.bank_name ?? "";
  phone.value = employee?.phone ?? "";
  workEmail.value = employee?.work_email ?? "";
  orgIds.value = employee?.org_id ? [employee.org_id] : [];
  positionId.value = employee?.position_id ?? "";
  jobLevel.value = employee?.job_level ?? "";
  hireDate.value = employee?.hire_date ?? new Date().toISOString().slice(0, 10);
  positionOptions.value = (await loadPositionOptions()) ?? [];
  if (!isEdit.value) await loadAttributeFields();
}, { immediate: true });

async function loadPositionOptions(): Promise<PositionOption[]> {
  // 无 hr:position:read 权限时降级空选项（岗位字段退化为不选）
  try {
    const res = await getPositionOptions();
    return res.data ?? [];
  } catch {
    return [];
  }
}

/** 预置属性组（basic/work/custom + 管理端自建组）定义 → DynamicForm 字段（name=definition_id） */
async function loadAttributeFields() {
  attributeFields.value = [];
  attributeInitial.value = {};
  try {
    const [groupsRes, definitionsRes] = await Promise.all([
      listFieldGroups(),
      listFieldDefinitions(),
    ]);
    const groups = groupsRes.data ?? [];
    const groupIds = new Set(
      groups.filter((group) => EAV_CREATE_GROUP_CODES.includes(group.code)).map((group) => group.id),
    );
    attributeFields.value = (definitionsRes.data ?? [])
      .filter((definition) => groupIds.has(definition.group_id))
      .map((definition) => ({
        name: definition.id,
        display_name: definition.name,
        data_type: definition.data_type,
        is_require: definition.is_require,
        can_edit: definition.can_edit,
        index: definition.sort,
        ext_data: definition.ext_data ?? undefined,
      }));
  } catch {
    attributeFields.value = [];
  }
}

function validateCurrentStep(): boolean {
  if (isEdit.value) return Boolean(name.value.trim());
  if (step.value === 0 && !name.value.trim()) {
    notifyError(new Error("请填写姓名"));
    return false;
  }
  if (step.value === 1 && !hireDate.value) {
    notifyError(new Error("请选择入职日期"));
    return false;
  }
  return true;
}

async function handleNext() {
  if (!validateCurrentStep()) return;
  if (step.value < stepTitles.length - 1) {
    step.value += 1;
    return;
  }
  await handleSubmit();
}

function handleBack() {
  if (step.value > 0) step.value -= 1;
}

async function handleSubmit() {
  submitting.value = true;
  try {
    if (isEdit.value) {
      if (!props.employee) return;
      const payload = {
        name: name.value,
        gender: gender.value || undefined,
        birth_date: birthDate.value || undefined,
        // 掩码/未变更时不下发，后端按「掩码/空 = 保留原值」处理
        id_card: idCard.value && idCard.value !== (props.employee as EmployeeDetail).id_card_masked ? idCard.value : undefined,
        bank_name: bankName.value || undefined,
        phone: phone.value || undefined,
        work_email: workEmail.value || undefined,
        org_id: orgIds.value[0] || undefined,
        position_id: positionId.value || undefined,
        job_level: jobLevel.value || undefined,
      };
      const res = await updateEmployee(props.employee.id, payload);
      notifySuccess("员工信息已更新");
      if (res.data) emit("saved", res.data);
    } else {
      let attributeValues: Record<string, unknown> | undefined;
      if (attributeFormRef.value) {
        if (!attributeFormRef.value.validate()) return;
        attributeValues = attributeFormRef.value.getValues();
      }
      const res = await createEmployee({
        name: name.value,
        gender: gender.value || undefined,
        birth_date: birthDate.value || undefined,
        id_card: idCard.value || undefined,
        bank_name: bankName.value || undefined,
        phone: phone.value || undefined,
        work_email: workEmail.value || undefined,
        org_id: orgIds.value[0] || undefined,
        position_id: positionId.value || undefined,
        job_level: jobLevel.value || undefined,
        hire_date: hireDate.value,
        attribute_values: attributeValues && Object.keys(attributeValues).length ? attributeValues : undefined,
      });
      notifySuccess("入职建档成功，工号已自动生成");
      if (res.data) emit("saved", res.data);
    }
    open.value = false;
  } catch (error) {
    notifyError(error, getErrorMessage(error, "保存失败"));
  } finally {
    submitting.value = false;
  }
}
</script>


<template>
  <Dialog v-model:open="open">
    <DialogContent class="flex max-h-[84vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl" data-testid="employee-form-modal">
      <DialogHeader class="shrink-0 border-b px-6 py-4">
        <DialogTitle>{{ isEdit ? "编辑员工" : "入职建档" }}</DialogTitle>
        <DialogDescription>
          {{ isEdit ? "修改员工主档信息；敏感字段留空或保持掩码表示保留原值。" : "分步录入新员工信息，提交后自动生成工号。" }}
        </DialogDescription>
      </DialogHeader>

      <!-- 步骤指示器 -->
      <div v-if="!isEdit" class="flex shrink-0 items-center gap-2 border-b px-6 py-3">
        <template v-for="(title, index) in stepTitles" :key="title">
          <span
            class="flex h-6 w-6 items-center justify-center rounded-full text-xs"
            :class="index === step ? 'bg-primary text-primary-foreground' : index < step ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground'"
          >
            {{ index + 1 }}
          </span>
          <span class="text-sm" :class="index === step ? 'font-medium' : 'text-muted-foreground'">{{ title }}</span>
          <span v-if="index < stepTitles.length - 1" class="bg-border h-px w-8" />
        </template>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto px-6 py-4">
        <!-- 步骤 1 / 编辑：基础信息 -->
        <div v-show="isEdit || step === 0" class="flex flex-col gap-4">
          <div class="grid grid-cols-2 gap-4">
            <div class="flex flex-col gap-1.5">
              <Label>姓名 <span class="text-destructive">*</span></Label>
              <Input v-model="name" placeholder="员工姓名" data-testid="employee-name-input" />
            </div>
            <div class="flex flex-col gap-1.5">
              <Label>性别</Label>
              <Select v-model="gender" :options="GENDER_OPTIONS" placeholder="请选择" />
            </div>
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div class="flex flex-col gap-1.5">
              <Label>出生日期</Label>
              <DateInput v-model="birthDate" />
            </div>
            <div class="flex flex-col gap-1.5">
              <Label>证件号</Label>
              <Input v-model="idCard" placeholder="身份证号（加密存储）" />
            </div>
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div class="flex flex-col gap-1.5">
              <Label>手机号</Label>
              <Input v-model="phone" placeholder="手机号" />
            </div>
            <div class="flex flex-col gap-1.5">
              <Label>工作邮箱</Label>
              <Input v-model="workEmail" placeholder="name@company.com" />
            </div>
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>开户行</Label>
            <Input v-model="bankName" placeholder="如 工商银行北京分行（代发导出用）" />
          </div>
        </div>

        <!-- 步骤 2：岗位任职 -->
        <div v-if="!isEdit" v-show="step === 1" class="flex flex-col gap-4">
          <div class="flex flex-col gap-1.5">
            <Label>所属组织</Label>
            <OrganizationSelect v-model="orgIds" :multiple="false" placeholder="选择组织" />
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div class="flex flex-col gap-1.5">
              <Label>入职日期 <span class="text-destructive">*</span></Label>
              <DateInput v-model="hireDate" data-testid="employee-hire-date-input" />
            </div>
            <div class="flex flex-col gap-1.5">
              <Label>职级</Label>
              <Input v-model="jobLevel" placeholder="如 P5" />
            </div>
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>岗位</Label>
            <Select
              v-model="positionId"
              :options="positionOptions.map((p) => ({ value: p.id, label: p.name }))"
              placeholder="选择岗位"
            />
          </div>
          <p class="text-muted-foreground text-xs">
            提交后系统自动生成工号并写入入职异动流水；员工初始状态为「待入职」。
          </p>
        </div>

        <!-- 步骤 3：扩展属性 -->
        <div v-if="!isEdit" v-show="step === 2" class="flex flex-col gap-4">
          <JsonRender
            v-if="attributeFields.length"
            :key="`employee-eav-${attributeFields.length}`"
            ref="attributeFormRef"
            :spec="attributeBuild.spec"
            :initial-state="attributeBuild.initialState"
          />
          <p v-else class="text-muted-foreground text-sm">当前租户暂无扩展属性定义，可直接提交。</p>
        </div>
      </div>

      <DialogFooter class="m-0 shrink-0 border-t px-6 py-3">
        <Button v-if="!isEdit && step > 0" variant="outline" @click="handleBack">上一步</Button>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="employee-form-submit" @click="handleNext">
          {{ !isEdit && step < stepTitles.length - 1 ? "下一步" : isEdit ? "保存" : "提交建档" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
