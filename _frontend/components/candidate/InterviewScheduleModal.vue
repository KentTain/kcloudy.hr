<script setup lang="ts">
/**
 * 安排面试弹窗：面试官（人员选择）/时间/形式；成功后建面试记录并流转申请至面试中。
 */
import { ref, watch } from "vue";

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

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import type { UserItem } from "@/components/common/feedback/people-select/types";

import { createInterview } from "@/hr/api/interview";
import { updateApplicationStage } from "@/hr/api/recruiting";
import { INTERVIEW_FORM_OPTIONS, type Application, type InterviewForm } from "@/hr/types/recruiting";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  application: Application | null;
}>();

const emit = defineEmits<{ saved: [] }>();

const submitting = ref(false);
const interviewerName = ref("");
const interviewerId = ref("");
const scheduledAt = ref("");
const interviewForm = ref<InterviewForm>("onsite");

const peoplePickerOpen = ref(false);

watch(open, (value) => {
  if (!value) return;
  // immediate：以 open=true 初始挂载（如测试或直开场景）也完成回填
  interviewerName.value = "";
  interviewerId.value = "";
  scheduledAt.value = "";
  interviewForm.value = "onsite";
}, { immediate: true });

function handlePeopleConfirm(userIds: string[], users: UserItem[]) {
  interviewerId.value = userIds[0] ?? "";
  interviewerName.value = users[0]?.nickname || users[0]?.username || "";
}

function validate(): string | null {
  if (!interviewerId.value) return "请选择面试官";
  if (!scheduledAt.value) return "请选择面试时间";
  return null;
}

async function handleSubmit() {
  const application = props.application;
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
    // 建面面记录后流转申请至面试中（状态机 screening_passed → interviewing）
    if (application.stage === "screening_passed") {
      await updateApplicationStage(application.id, "interviewing");
    }
    notifySuccess("面试已安排，申请已进入面试中");
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
    <DialogContent class="sm:max-w-md" data-testid="interview-schedule-dialog">
      <DialogHeader>
        <DialogTitle>安排面试</DialogTitle>
        <DialogDescription>
          {{ application?.candidate_name ?? "--" }} · {{ application?.requisition_title ?? "--" }}；轮次自动递增。
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4">
        <div class="flex flex-col gap-1.5">
          <Label>面试官 *</Label>
          <div class="flex items-center gap-2">
            <Input :model-value="interviewerName" readonly placeholder="点选选择面试官" data-testid="interview-interviewer-input" class="flex-1" />
            <Button variant="outline" size="sm" data-testid="interview-pick-interviewer" @click="peoplePickerOpen = true">
              选择
            </Button>
          </div>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>面试时间 *</Label>
          <Input v-model="scheduledAt" type="datetime-local" data-testid="interview-time-input" />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>面试形式</Label>
          <Select v-model="interviewForm" :options="INTERVIEW_FORM_OPTIONS" data-testid="interview-form-select" />
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="interview-submit" @click="handleSubmit">
          {{ submitting ? "提交中…" : "安排" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>

  <PeopleSelectDialog v-model:open="peoplePickerOpen" :multiple="false" @confirm="handlePeopleConfirm" />
</template>
