<script setup lang="ts">
/**
 * 面试评价弹窗：结论（通过自动流转拟录用）/反馈/改期 + AI 纪要任务化生成
 * （提交任务 → 轮询面试详情直至纪要回写，进行中重复提交幂等）+ AI 追问建议
 * （即时生成不落库，点击问题插入反馈框；失败降级手动填写）。
 */
import { onUnmounted, ref, watch } from "vue";

import { Button, Input, Select, Textarea } from "@/components";
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

import {
  getFollowupQuestions,
  getInterviewDetail,
  submitInterviewSummary,
  updateInterview,
} from "@/hr/api/interview";
import {
  INTERVIEW_FORM_LABELS,
  type InterviewDayItem,
  type InterviewForm,
} from "@/hr/types/recruiting";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  interview: InterviewDayItem | null;
}>();

const emit = defineEmits<{ saved: [] }>();

const submitting = ref(false);
const result = ref<"pass" | "fail">("pass");
const feedback = ref("");
const scheduledAt = ref("");
const aiSummary = ref("");
const summarySubmitting = ref(false);
const summaryPending = ref(false);
const questions = ref<string[]>([]);
const questionsLoading = ref(false);
let summaryPollTimer: ReturnType<typeof setTimeout> | null = null;

const SUMMARY_POLL_INTERVAL = 2000;
const SUMMARY_POLL_MAX_ROUNDS = 15;

const resultOptions = [
  { value: "pass", label: "通过" },
  { value: "fail", label: "未通过" },
];

watch(open, (value) => {
  if (!value) {
    stopSummaryPolling();
    return;
  }
  // immediate：以 open=true 初始挂载（如测试或直开场景）也完成回填
  result.value = "pass";
  feedback.value = "";
  aiSummary.value = "";
  summaryPending.value = false;
  questions.value = [];
  const raw = props.interview?.scheduled_at ?? "";
  scheduledAt.value = raw ? raw.slice(0, 16) : "";
}, { immediate: true });

onUnmounted(() => stopSummaryPolling());

/* ── AI 纪要（任务化 + 轮询回写） ── */

function stopSummaryPolling() {
  if (summaryPollTimer) {
    clearTimeout(summaryPollTimer);
    summaryPollTimer = null;
  }
}

async function handleGenerateSummary() {
  if (!props.interview || summarySubmitting.value) return;
  summarySubmitting.value = true;
  try {
    const res = await submitInterviewSummary(props.interview.id);
    const data = res.data;
    if (!data?.task_id) {
      notifyError(new Error("纪要任务提交失败，可后补重试"));
      return;
    }
    if (data.duplicated) {
      notifySuccess("已有纪要生成任务进行中，等待完成…");
    }
    summaryPending.value = true;
    startSummaryPolling(props.interview.id, 0);
  } catch (error) {
    notifyError(error, getErrorMessage(error, "纪要任务提交失败，可后补重试"));
  } finally {
    summarySubmitting.value = false;
  }
}

function startSummaryPolling(interviewId: string, round: number) {
  stopSummaryPolling();
  if (round >= SUMMARY_POLL_MAX_ROUNDS) {
    summaryPending.value = false;
    notifyError(new Error("纪要仍在生成中，请稍后重新打开查看"));
    return;
  }
  summaryPollTimer = setTimeout(() => {
    void pollSummary(interviewId, round + 1);
  }, SUMMARY_POLL_INTERVAL);
}

async function pollSummary(interviewId: string, round: number) {
  try {
    const res = await getInterviewDetail(interviewId);
    const summary = res.data?.ai_summary;
    if (summary) {
      summaryPending.value = false;
      aiSummary.value = summary;
      notifySuccess("AI 纪要已生成");
      return;
    }
  } catch {
    // 轮询失败静默重试（下一轮继续）
  }
  startSummaryPolling(interviewId, round);
}

/* ── AI 追问建议 ── */

async function handleFollowupQuestions() {
  if (!props.interview || questionsLoading.value) return;
  questionsLoading.value = true;
  try {
    const res = await getFollowupQuestions(props.interview.id);
    questions.value = res.data?.questions ?? [];
    if (!questions.value.length) {
      notifyError(new Error("未生成追问建议，请手动填写反馈"));
    }
  } catch (error) {
    notifyError(error, getErrorMessage(error, "追问建议生成失败，请手动填写"));
  } finally {
    questionsLoading.value = false;
  }
}

function applyQuestion(question: string) {
  feedback.value = feedback.value ? `${feedback.value}\n${question}` : question;
}

async function handleSubmit() {
  const interview = props.interview;
  if (!interview) return;
  submitting.value = true;
  try {
    const payload: { result: string; feedback?: string; scheduled_at?: string } = {
      result: result.value,
    };
    if (feedback.value.trim()) payload.feedback = feedback.value.trim();
    if (scheduledAt.value && scheduledAt.value !== interview.scheduled_at.slice(0, 16)) {
      payload.scheduled_at = scheduledAt.value;
    }
    await updateInterview(interview.id, payload);
    notifySuccess(
      result.value === "pass" ? "面试通过，申请已流转拟录用" : "面试结论已提交",
    );
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "面试评价提交失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-md" data-testid="interview-review-dialog">
      <DialogHeader>
        <DialogTitle>面试评价</DialogTitle>
        <DialogDescription>
          {{ interview?.candidate_name ?? "--" }} · {{ interview?.requisition_title ?? "--" }} · 第
          {{ interview?.round ?? "--" }} 轮 ·
          {{ interview ? (INTERVIEW_FORM_LABELS[interview.interview_form as InterviewForm] ?? interview.interview_form) : "--" }}
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4">
        <div class="flex flex-col gap-1.5">
          <Label>面试时间（改期将通知面试官）</Label>
          <Input v-model="scheduledAt" type="datetime-local" data-testid="interview-review-time-input" />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>结论 *</Label>
          <Select v-model="result" :options="resultOptions" data-testid="interview-review-result-select" />
        </div>
        <div class="flex flex-col gap-1.5">
          <div class="flex items-center justify-between">
            <Label>面试反馈</Label>
            <div class="flex gap-3">
              <Button
                variant="link"
                size="sm"
                class="h-auto p-0"
                :disabled="questionsLoading"
                data-testid="interview-review-questions"
                @click="handleFollowupQuestions"
              >
                {{ questionsLoading ? "生成中…" : "AI 追问建议" }}
              </Button>
              <Button
                variant="link"
                size="sm"
                class="h-auto p-0"
                :disabled="summarySubmitting"
                data-testid="interview-review-ai-summary"
                @click="handleGenerateSummary"
              >
                {{ summaryPending ? "纪要生成中…" : "生成 AI 纪要" }}
              </Button>
            </div>
          </div>
          <Textarea v-model="feedback" rows="4" placeholder="面试表现与评价" data-testid="interview-review-feedback-input" />
          <div v-if="questions.length" class="flex flex-col gap-1" data-testid="interview-review-questions-list">
            <button
              v-for="question in questions"
              :key="question"
              type="button"
              class="bg-muted text-muted-foreground hover:bg-muted/70 rounded-md px-3 py-1.5 text-left text-xs"
              :data-testid="`interview-review-question-item`"
              title="点击插入反馈"
              @click="applyQuestion(question)"
            >
              {{ question }}
            </button>
          </div>
          <p
            v-if="aiSummary"
            class="text-muted-foreground rounded-md border px-3 py-2 text-xs whitespace-pre-wrap"
            data-testid="interview-review-summary-text"
          >
            {{ aiSummary }}
          </p>
          <p v-else-if="summaryPending" class="text-muted-foreground text-xs" data-testid="interview-review-summary-pending">
            AI 纪要生成中，完成后自动展示…
          </p>
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="interview-review-submit" @click="handleSubmit">
          {{ submitting ? "提交中…" : "提交结论" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
