<script setup lang="ts">
/**
 * 评分弹窗：得分/评级必填，自评分选填（自评链路主要走 console，admin 可代录）。
 * 仅评分中周期可提交；已校准评估锁定（后端 409 兜底）。
 */
import { ref, watch } from "vue";

import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Input, Label, Select } from "@/components";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { scorePerfReview } from "@/hr/api/perf";
import { PERF_RATINGS, type PerfReviewItem } from "@/hr/types/perf";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{ review: PerfReviewItem | null }>();

const emit = defineEmits<{ saved: [] }>();

const ALL = "__rating__";

const score = ref("");
const rating = ref(ALL);
const selfScore = ref("");
const submitting = ref(false);

watch(open, (value) => {
  if (!value) return;
  score.value = props.review?.score != null ? String(props.review.score) : "";
  rating.value = props.review?.rating ?? ALL;
  selfScore.value = props.review?.self_score != null ? String(props.review.self_score) : "";
});

async function handleSubmit() {
  const scoreValue = Number(score.value);
  if (!score.value || Number.isNaN(scoreValue)) {
    notifyError(new Error("请填写得分"), "请填写得分");
    return;
  }
  if (rating.value === ALL) {
    notifyError(new Error("请选择评级"), "请选择评级");
    return;
  }
  if (!props.review) return;
  submitting.value = true;
  try {
    await scorePerfReview(props.review.id, {
      score: scoreValue,
      rating: rating.value,
      ...(selfScore.value ? { self_score: Number(selfScore.value) } : {}),
    });
    notifySuccess("评分已提交");
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "评分提交失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-md" data-testid="review-score-modal">
      <DialogHeader>
        <DialogTitle>评估评分</DialogTitle>
        <DialogDescription>
          {{ review?.employee_name ?? "" }} · 得分与初评评级提交后进入校准环节
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4 py-2">
        <div class="flex flex-col gap-2">
          <Label>得分</Label>
          <Input
            v-model="score"
            type="number"
            placeholder="0-100"
            data-testid="review-score-value"
          />
        </div>
        <div class="flex flex-col gap-2">
          <Label>初评评级</Label>
          <Select
            v-model="rating"
            :options="[
              { value: ALL, label: '请选择' },
              ...PERF_RATINGS.map((item) => ({ value: item, label: item })),
            ]"
            data-testid="review-score-rating"
          />
        </div>
        <div class="flex flex-col gap-2">
          <Label>自评分（选填）</Label>
          <Input
            v-model="selfScore"
            type="number"
            placeholder="员工自评分"
            data-testid="review-score-self"
          />
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" data-testid="review-score-cancel" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="review-score-submit" @click="handleSubmit">
          提交
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
