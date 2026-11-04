<script setup lang="ts">
/**
 * 校准弹窗：最终评级 + 校准意见（必填留痕：操作人/前后评级/时间由后端写入）。
 * 仅校准中周期且评估已提交初评可操作（hr:perf:calibrate 权限门控在页面）。
 */
import { ref, watch } from "vue";

import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Label, Select, Textarea } from "@/components";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { calibratePerfReview } from "@/hr/api/perf";
import { PERF_RATINGS, type PerfReviewItem } from "@/hr/types/perf";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{ review: PerfReviewItem | null }>();

const emit = defineEmits<{ saved: [] }>();

const ALL = "__rating__";

const rating = ref(ALL);
const comment = ref("");
const submitting = ref(false);

watch(open, (value) => {
  if (!value) return;
  rating.value = props.review?.calibrated_rating ?? props.review?.rating ?? ALL;
  comment.value = "";
});

async function handleSubmit() {
  if (rating.value === ALL) {
    notifyError(new Error("请选择最终评级"), "请选择最终评级");
    return;
  }
  if (!comment.value.trim()) {
    notifyError(new Error("校准意见必填"), "校准意见必填");
    return;
  }
  if (!props.review) return;
  submitting.value = true;
  try {
    await calibratePerfReview(props.review.id, {
      rating: rating.value,
      comment: comment.value.trim(),
    });
    notifySuccess("校准已留痕");
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "校准失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-md" data-testid="review-calibrate-modal">
      <DialogHeader>
        <DialogTitle>评级校准</DialogTitle>
        <DialogDescription>
          {{ review?.employee_name ?? "" }} · 初评
          {{ review?.rating ?? "—" }} → 最终评级；意见必填并留痕（操作人/前后评级/时间）
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4 py-2">
        <div class="flex flex-col gap-2">
          <Label>最终评级</Label>
          <Select
            v-model="rating"
            :options="[
              { value: ALL, label: '请选择' },
              ...PERF_RATINGS.map((item) => ({ value: item, label: item })),
            ]"
            data-testid="review-calibrate-rating"
          />
        </div>
        <div class="flex flex-col gap-2">
          <Label>校准意见</Label>
          <Textarea
            v-model="comment"
            :rows="4"
            placeholder="校准理由（强制分布参考、业绩说明等）"
            data-testid="review-calibrate-comment"
          />
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" data-testid="review-calibrate-cancel" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="review-calibrate-submit" @click="handleSubmit">
          校准
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
