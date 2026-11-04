<script setup lang="ts">
/**
 * 岗位表单弹窗（创建/编辑）：编码租户唯一（409 冲突提示）、组织弱引用、职级/编制
 */
import { computed, ref, watch } from "vue";

import { Input, Select } from "@/components";
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

import { createPosition, updatePosition } from "@/hr/api/position";
import {
  POSITION_STATUS_LABELS,
  type Position,
  type PositionStatus,
} from "@/hr/types/position";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  mode: "create" | "edit";
  position: Position | null;
}>();

const emit = defineEmits<{ saved: [] }>();

const submitting = ref(false);
const code = ref("");
const name = ref("");
const orgIds = ref<string[]>([]);
const jobLevel = ref("");
const headcountInput = ref("");
const status = ref<PositionStatus>("active");

const statusOptions = (
  Object.entries(POSITION_STATUS_LABELS) as [PositionStatus, string][]
).map(([value, label]) => ({ value, label }));

const isEdit = computed(() => props.mode === "edit");

watch(open, (value) => {
  if (!value) return;
  code.value = props.position?.code ?? "";
  name.value = props.position?.name ?? "";
  orgIds.value = props.position?.org_id ? [props.position.org_id] : [];
  jobLevel.value = props.position?.job_level ?? "";
  headcountInput.value =
    props.position?.headcount === null || props.position?.headcount === undefined
      ? ""
      : String(props.position.headcount);
  status.value = props.position?.status ?? "active";
});

async function handleSubmit() {
  if (!code.value.trim()) {
    notifyError(new Error("请填写岗位编码"));
    return;
  }
  if (!name.value.trim()) {
    notifyError(new Error("请填写岗位名称"));
    return;
  }
  const headcount = headcountInput.value.trim() === "" ? undefined : Number(headcountInput.value);
  if (headcount !== undefined && (!Number.isInteger(headcount) || headcount < 0)) {
    notifyError(new Error("编制数须为非负整数"));
    return;
  }
  submitting.value = true;
  try {
    const orgId = orgIds.value[0];
    if (isEdit.value && props.position) {
      await updatePosition(props.position.id, {
        code: code.value.trim(),
        name: name.value.trim(),
        org_id: orgId,
        job_level: jobLevel.value.trim() || undefined,
        headcount,
        status: status.value,
      });
      notifySuccess("岗位已更新");
    } else {
      await createPosition({
        code: code.value.trim(),
        name: name.value.trim(),
        org_id: orgId,
        job_level: jobLevel.value.trim() || undefined,
        headcount,
      });
      notifySuccess("岗位已创建");
    }
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, isEdit.value ? "岗位更新失败" : "岗位创建失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-md" data-testid="position-form-dialog">
      <DialogHeader>
        <DialogTitle>{{ isEdit ? "编辑岗位" : "新增岗位" }}</DialogTitle>
        <DialogDescription>岗位编码租户内唯一；停用岗位不可被员工建档与招聘需求选中。</DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4">
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-1.5">
            <Label>岗位编码 *</Label>
            <Input v-model="code" placeholder="如 BE-ENG" data-testid="position-code-input" />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>岗位名称 *</Label>
            <Input v-model="name" placeholder="如 后端工程师" data-testid="position-name-input" />
          </div>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>所属组织</Label>
          <OrganizationSelect v-model="orgIds" :multiple="false" placeholder="选择组织" />
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-1.5">
            <Label>职级</Label>
            <Input v-model="jobLevel" placeholder="如 P5 / M2" data-testid="position-job-level-input" />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>编制数</Label>
            <Input
              v-model="headcountInput"
              type="number"
              min="0"
              placeholder="不填表示不限"
              data-testid="position-headcount-input"
            />
          </div>
        </div>
        <div v-if="isEdit" class="flex flex-col gap-1.5">
          <Label>状态</Label>
          <Select v-model="status" :options="statusOptions" data-testid="position-status-select" />
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="position-submit" @click="handleSubmit">
          {{ submitting ? "保存中…" : "保存" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
