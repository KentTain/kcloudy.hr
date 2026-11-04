<script setup lang="ts">
/**
 * NL 问数弹窗：自然语言提问 → 白名单指标聚合回答（附指标口径说明）；
 * 越界指标后端 400，弹窗内展示提示不猜指标。
 */
import { ref, watch } from "vue";

import { Badge, Button, Input } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components";

import { getErrorMessage } from "@/framework/utils/feedback";

import { askReport } from "@/hr/api/report";
import type { ReportAskData } from "@/hr/types/report";

const open = defineModel<boolean>("open", { required: true });

const question = ref("");
const loading = ref(false);
const result = ref<ReportAskData | null>(null);
const errorText = ref("");

watch(open, (value) => {
  if (!value) return;
  question.value = "";
  result.value = null;
  errorText.value = "";
});

async function handleAsk() {
  const text = question.value.trim();
  if (!text || loading.value) return;
  loading.value = true;
  result.value = null;
  errorText.value = "";
  try {
    const res = await askReport(text);
    result.value = res.data ?? null;
    if (!result.value) errorText.value = "未能获取回答，请稍后重试";
  } catch (error) {
    errorText.value = getErrorMessage(error, "问数失败，请调整提问后重试");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-lg" data-testid="report-ask-dialog">
      <DialogHeader>
        <DialogTitle>AI 问数</DialogTitle>
        <DialogDescription>
          用自然语言提问人事/招聘/薪酬/绩效白名单指标，仅聚合口径不返回明细。
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-3">
        <div class="flex gap-2">
          <Input
            v-model="question"
            placeholder="如：最近 3 个月离职率如何？"
            data-testid="report-ask-input"
            @keyup.enter="handleAsk"
          />
          <Button :disabled="loading || !question.trim()" data-testid="report-ask-submit" @click="handleAsk">
            {{ loading ? "分析中…" : "提问" }}
          </Button>
        </div>
        <p v-if="errorText" class="text-destructive text-xs" data-testid="report-ask-error">
          {{ errorText }}
        </p>
        <div v-if="result" class="flex flex-col gap-2" data-testid="report-ask-result">
          <div class="flex flex-wrap items-center gap-2">
            <Badge data-testid="report-ask-metric">{{ result.metric }}</Badge>
            <Badge variant="outline">{{ result.source === "keyword" ? "规则匹配" : "AI 匹配" }}</Badge>
          </div>
          <p class="text-sm whitespace-pre-wrap" data-testid="report-ask-answer">{{ result.answer }}</p>
          <p class="text-muted-foreground text-xs" data-testid="report-ask-ref">口径：{{ result.metric_ref }}</p>
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" data-testid="report-ask-close" @click="open = false">关闭</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
