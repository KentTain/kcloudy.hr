<script setup lang="ts">
/**
 * 日程页快捷安排面试弹窗：需求 → 候选人（可安排阶段）→ 时间/形式/面试官。
 * 提交创建面试记录；首轮（初筛通过）自动流转申请至面试中。
 */
import { computed, ref, watch } from "vue";

import { Button, Input, Select } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components";
import { Label } from "@/components";
import { PeopleSelectDialog } from "@/components";

import type { UserItem } from "@/components/common/feedback/people-select/types";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { createInterview } from "@/hr/api/interview";
import { listCandidateCards } from "@/hr/api/candidate";
import { listRequisitions, updateApplicationStage } from "@/hr/api/recruiting";
import {
  APPLICATION_STAGE_LABELS,
  INTERVIEW_FORM_OPTIONS,
  type Application,
  type InterviewForm,
} from "@/hr/types/recruiting";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  /** 快捷入口预填日期（YYYY-MM-DD），时间默认该日 09:00 */
  presetDate?: string | null;
}>();

const emit = defineEmits<{ saved: [] }>();

/** 可安排面试的申请阶段（终态与未过筛禁安排） */
const SCHEDULABLE_STAGES = new Set(["screening_passed", "interviewing"]);

const submitting = ref(false);
const requisitionId = ref("__none__");
const applicationId = ref("__none__");
const interviewerId = ref("");
const interviewerName = ref("");
const scheduledAt = ref("");
const interviewForm = ref<InterviewForm>("onsite");

const peoplePickerOpen = ref(false);
const requisitionOptions = ref<{ value: string; label: string }[]>([]);
const applicationOptions = ref<{ value: string; label: string }[]>([]);
const loadedApplications = ref<Application[]>([]);

const pickedApplication = computed(() =>
  loadedApplications.value.find((item) => item.id === applicationId.value) ?? null,
);

watch(open, async (value) => {
  if (!value) return;
  // immediate：以 open=true 初始挂载（如测试或直开场景）也完成回填
  requisitionId.value = "__none__";
  applicationId.value = "__none__";
  interviewerId.value = "";
  interviewerName.value = "";
  interviewForm.value = "onsite";
  scheduledAt.value = props.presetDate ? `${props.presetDate}T09:00` : "";
  applicationOptions.value = [];
  loadedApplications.value = [];
  try {
    const res = await listRequisitions({ page: 1, page_size: 100 });
    requisitionOptions.value = [
      { value: "__none__", label: "请选择需求" },
      ...(res.data ?? [])
        .filter((item) => item.status !== "closed")
        .map((item) => ({ value: item.id, label: `${item.title}（${item.req_no}）` })),
    ];
  } catch {
    requisitionOptions.value = [{ value: "__none__", label: "请选择需求" }];
  }
}, { immediate: true });

async function handleRequisitionChange() {
  applicationId.value = "__none__";
  applicationOptions.value = [];
  loadedApplications.value = [];
  if (requisitionId.value === "__none__") return;
  try {
    const res = await listCandidateCards({ requisition_id: requisitionId.value, page: 1, page_size: 100 });
    loadedApplications.value = (res.data ?? []).filter((item) => SCHEDULABLE_STAGES.has(item.stage));
    applicationOptions.value = [
      { value: "__none__", label: "请选择候选人" },
      ...loadedApplications.value.map((item) => ({
        value: item.id,
        label: `${item.candidate_name ?? item.candidate_id}（${APPLICATION_STAGE_LABELS[item.stage]}）`,
      })),
    ];
  } catch (error) {
    notifyError(error, getErrorMessage(error, "候选人加载失败"));
  }
}

function handlePeopleConfirm(userIds: string[], users: UserItem[]) {
  interviewerId.value = userIds[0] ?? "";
  interviewerName.value = users[0]?.nickname || users[0]?.username || "";
}

function validate(): string | null {
  if (applicationId.value === "__none__") return "请选择候选人";
  if (!interviewerId.value) return "请选择面试官";
  if (!scheduledAt.value) return "请选择面试时间";
  return null;
}

async function handleSubmit() {
  const application = pickedApplication.value;
  if (!application) return;
  const error = validate();
  if (error) {
    notifyError(new Error(error));
    return;
  }
  submitting.value = true;
  try {
    await createInterview(application.id, {
      interviewer_id: interviewerId.value,
      scheduled_at: scheduledAt.value,
      interview_form: interviewForm.value,
    });
    // 建面试记录后流转申请至面试中（首轮：状态机 screening_passed → interviewing）
    if (application.stage === "screening_passed") {
      await updateApplicationStage(application.id, "interviewing");
    }
    notifySuccess("面试已安排");
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "安排面试失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-md" data-testid="interview-quick-dialog">
      <DialogHeader>
        <DialogTitle>安排面试</DialogTitle>
        <DialogDescription>轮次自动递增；初筛通过的候选人安排后将进入面试中。</DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4">
        <div class="flex flex-col gap-1.5">
          <Label>需求 *</Label>
          <Select
            v-model="requisitionId"
            :options="requisitionOptions"
            data-testid="interview-quick-requisition-select"
            @update:model-value="handleRequisitionChange"
          />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>候选人 *</Label>
          <Select
            v-model="applicationId"
            :options="applicationOptions"
            :disabled="requisitionId === '__none__'"
            data-testid="interview-quick-application-select"
          />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>面试官 *</Label>
          <div class="flex items-center gap-2">
            <Input :model-value="interviewerName" readonly placeholder="点选选择面试官" data-testid="interview-quick-interviewer-input" class="flex-1" />
            <Button variant="outline" size="sm" data-testid="interview-quick-pick-interviewer" @click="peoplePickerOpen = true">
              选择
            </Button>
          </div>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>面试时间 *</Label>
          <Input v-model="scheduledAt" type="datetime-local" data-testid="interview-quick-time-input" />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>面试形式</Label>
          <Select v-model="interviewForm" :options="INTERVIEW_FORM_OPTIONS" data-testid="interview-quick-form-select" />
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="interview-quick-submit" @click="handleSubmit">
          {{ submitting ? "提交中…" : "安排" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>

  <PeopleSelectDialog v-model:open="peoplePickerOpen" :multiple="false" @confirm="handlePeopleConfirm" />
</template>
