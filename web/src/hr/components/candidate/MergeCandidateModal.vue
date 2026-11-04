<script setup lang="ts">
/**
 * 候选人合并弹窗：疑似重复档建议（手机/邮箱命中，直选目标）+ 关键词检索
 * （source 投递/面试归并到 target 后删除 source）。
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

import { getErrorMessage, notifyError, notifySuccess, confirmAction } from "@/framework/utils/feedback";

import { getMergeSuggestions, listCandidateCards, mergeCandidates } from "@/hr/api/candidate";
import type { Application, MergeSuggestion } from "@/hr/types/recruiting";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  /** 合并源候选人（投递/面试归并出的一方） */
  source: { id: string; name: string } | null;
}>();

const emit = defineEmits<{ merged: [] }>();

const keyword = ref("");
const rows = ref<Application[]>([]);
const loading = ref(false);
const suggestions = ref<MergeSuggestion[]>([]);
const target = ref<{ candidate_id: string; candidate_name: string | null } | null>(null);

async function loadSuggestions() {
  if (!props.source) {
    suggestions.value = [];
    return;
  }
  try {
    const res = await getMergeSuggestions(props.source.id);
    suggestions.value = res.data ?? [];
  } catch {
    suggestions.value = [];
  }
}

async function search() {
  loading.value = true;
  try {
    const res = await listCandidateCards({ page: 1, page_size: 20, keyword: keyword.value || undefined });
    const seen = new Set<string>(props.source ? [props.source.id] : []);
    rows.value = (res.data ?? []).filter((item) => {
      if (seen.has(item.candidate_id)) return false;
      seen.add(item.candidate_id);
      return true;
    });
  } catch (error) {
    notifyError(error, getErrorMessage(error, "候选人检索失败"));
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

watch(open, async (value) => {
  if (!value) return;
  // immediate：以 open=true 初始挂载（如测试或直开场景）也完成回填
  keyword.value = "";
  target.value = null;
  await Promise.all([loadSuggestions(), search()]);
}, { immediate: true });

function pickTarget(candidateId: string, candidateName: string | null) {
  target.value = { candidate_id: candidateId, candidate_name: candidateName };
}

async function handleMerge() {
  if (!props.source || !target.value) return;
  if (
    !(await confirmAction(
      `确定将「${props.source.name}」合并到「${target.value.candidate_name ?? target.value.candidate_id}」？投递与面试记录将归并，原档案删除且不可恢复。`,
    ))
  ) {
    return;
  }
  try {
    const result = await mergeCandidates(props.source.id, target.value.candidate_id);
    notifySuccess(`合并完成，归并投递 ${result.data?.merged_applications ?? 0} 条`);
    open.value = false;
    emit("merged");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "候选人合并失败"));
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-md" data-testid="merge-candidate-dialog">
      <DialogHeader>
        <DialogTitle>合并候选人</DialogTitle>
        <DialogDescription>
          将「{{ source?.name ?? "--" }}」的投递与面试记录归并到另一档案；合并后原档案删除。
        </DialogDescription>
      </DialogHeader>
      <div class="flex items-center gap-2">
        <Input
          v-model="keyword"
          class="flex-1"
          placeholder="姓名/手机/邮箱"
          data-testid="merge-keyword-input"
          @keyup.enter="search"
        />
        <Button variant="outline" size="sm" data-testid="merge-search" @click="search">搜索</Button>
      </div>
      <div v-if="suggestions.length" class="flex flex-col gap-1.5">
        <p class="text-muted-foreground text-xs">疑似重复档（手机/邮箱命中，点击直选目标）</p>
        <button
          v-for="item in suggestions"
          :key="item.candidate_id"
          type="button"
          class="flex items-center justify-between rounded-md border border-dashed px-3 py-2 text-left text-sm hover:bg-accent"
          :class="target?.candidate_id === item.candidate_id ? 'border-primary bg-primary/10' : ''"
          :data-testid="`merge-suggestion-${item.candidate_id}`"
          @click="pickTarget(item.candidate_id, item.name)"
        >
          <span>{{ item.name }}</span>
          <span class="text-muted-foreground flex items-center gap-2 text-xs">
            {{ item.phone ?? item.email ?? "" }}
            <Badge variant="secondary">{{ item.matched_by === "phone" ? "手机命中" : "邮箱命中" }}</Badge>
          </span>
        </button>
      </div>
      <div class="flex max-h-64 flex-col gap-1.5 overflow-auto rounded-md border p-2">
        <button
          v-for="row in rows"
          :key="row.id"
          type="button"
          class="flex items-center justify-between rounded-md border px-3 py-2 text-left text-sm hover:bg-accent"
          :class="target?.candidate_id === row.candidate_id ? 'border-primary bg-primary/10' : ''"
          :data-testid="`merge-target-${row.candidate_id}`"
          @click="pickTarget(row.candidate_id, row.candidate_name)"
        >
          <span>{{ row.candidate_name ?? row.candidate_id }}</span>
          <span class="text-muted-foreground text-xs">{{ row.requisition_title ?? "" }}</span>
        </button>
        <p v-if="!rows.length && !loading" class="text-muted-foreground px-2 py-4 text-center text-sm">
          无匹配候选人
        </p>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="!target" data-testid="merge-submit" @click="handleMerge">确认合并</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
