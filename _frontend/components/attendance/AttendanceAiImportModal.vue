<script setup lang="ts">
/**
 * AI 导入弹窗：上传考勤文档 → 创建解析批次 → 轮询解析进度 → 行级预览
 * （默认勾选可解析行，未匹配员工/字段缺失行不勾选）→ 确认导入 → 批次反馈；
 * 解析失败可重新解析（原文档留存）。
 */
import { computed, onUnmounted, ref, watch } from "vue";

import { Badge, Button } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import {
  confirmAiImportBatch,
  createAiImportBatch,
  exportAiBatchFailures,
  getAiImportBatch,
  listAiImportBatches,
  retryAiImportBatch,
} from "@/hr/api/attendance";
import { downloadBase64File } from "@/hr/utils/download";
import {
  ATTENDANCE_BATCH_STATUS_LABELS,
  type AttendanceBatch,
  type AttendanceBatchStatus,
} from "@/hr/types/attendance";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ "update:open": [value: boolean]; saved: [] }>();

type Step = "upload" | "parsing" | "preview" | "result";

const step = ref<Step>("upload");
const fileInput = ref<HTMLInputElement | null>(null);
const selectedFile = ref<File | null>(null);
const batch = ref<AttendanceBatch | null>(null);
const submitting = ref(false);
const selectedRows = ref<Set<number>>(new Set());
const historyBatches = ref<AttendanceBatch[]>([]);
const downloadingId = ref<string | null>(null);
let pollTimer: ReturnType<typeof setInterval> | null = null;

const canConfirm = computed(() => selectedRows.value.size > 0);
const progressStatus = computed<AttendanceBatchStatus | null>(() => batch.value?.status ?? null);

watch(
  () => props.open,
  (open) => {
    if (open) {
      resetState();
      void loadHistory();
    } else {
      stopPolling();
    }
  },
);

onUnmounted(() => stopPolling());

function resetState() {
  stopPolling();
  step.value = "upload";
  selectedFile.value = null;
  batch.value = null;
  selectedRows.value = new Set();
  submitting.value = false;
  if (fileInput.value) fileInput.value.value = "";
}

function pickFile() {
  fileInput.value?.click();
}

/* ── 历史批次回看与失败明细下载 ── */

async function loadHistory() {
  try {
    const res = await listAiImportBatches({ page: 1, page_size: 10 });
    historyBatches.value = res.data?.items ?? [];
  } catch {
    historyBatches.value = [];
  }
}

async function downloadFailures(item: AttendanceBatch) {
  if (downloadingId.value) return;
  downloadingId.value = item.id;
  try {
    const res = await exportAiBatchFailures(item.id);
    const file = res.data;
    if (!file?.content_base64) {
      notifyError(new Error("失败明细文件生成失败"));
      return;
    }
    downloadBase64File(file.filename, file.content_base64);
  } catch (error) {
    notifyError(error, getErrorMessage(error, "失败明细下载失败"));
  } finally {
    downloadingId.value = null;
  }
}

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  selectedFile.value = input.files?.[0] ?? null;
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function startPolling(batchId: string) {
  stopPolling();
  pollTimer = setInterval(() => {
    void pollBatch(batchId);
  }, 2000);
  void pollBatch(batchId);
}

async function pollBatch(batchId: string) {
  try {
    const res = await getAiImportBatch(batchId);
    const data = res.data;
    if (!data) return;
    batch.value = data;
    if (data.status === "parsed") {
      stopPolling();
      enterPreview(data);
    } else if (data.status === "failed" || data.status === "completed") {
      stopPolling();
      if (data.status === "failed") step.value = "parsing";
    }
  } catch {
    // 轮询失败静默重试（下一轮继续）
  }
}

function enterPreview(data: AttendanceBatch) {
  selectedRows.value = new Set(
    (data.row_results ?? []).filter((row) => row.parseable).map((row) => row.row_index),
  );
  step.value = "preview";
}

async function startParse() {
  if (!selectedFile.value) {
    notifyError(new Error("请先选择考勤文档"));
    return;
  }
  submitting.value = true;
  try {
    const res = await createAiImportBatch(selectedFile.value);
    batch.value = res.data ?? null;
    if (batch.value?.id) {
      step.value = "parsing";
      startPolling(batch.value.id);
    }
  } catch (error) {
    notifyError(error, getErrorMessage(error, "上传失败"));
  } finally {
    submitting.value = false;
  }
}

async function retryParse() {
  if (!batch.value?.id) return;
  submitting.value = true;
  try {
    const res = await retryAiImportBatch(batch.value.id);
    batch.value = res.data ?? batch.value;
    startPolling(batch.value.id);
  } catch (error) {
    notifyError(error, getErrorMessage(error, "重新解析失败"));
  } finally {
    submitting.value = false;
  }
}

function toggleRow(rowIndex: number) {
  const next = new Set(selectedRows.value);
  if (next.has(rowIndex)) next.delete(rowIndex);
  else next.add(rowIndex);
  selectedRows.value = next;
}

async function confirmImport() {
  if (!batch.value?.id || !canConfirm.value) return;
  submitting.value = true;
  try {
    const res = await confirmAiImportBatch(batch.value.id, [...selectedRows.value].sort((a, b) => a - b));
    batch.value = res.data ?? batch.value;
    step.value = "result";
    notifySuccess(
      `导入完成：新增 ${batch.value?.new_count ?? 0} 条，覆盖 ${batch.value?.overwrite_count ?? 0} 条，丢弃 ${(batch.value?.row_results ?? []).length - selectedRows.value.size} 行`,
    );
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "导入失败"));
  } finally {
    submitting.value = false;
  }
}

function close() {
  emit("update:open", false);
}
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-2xl" data-testid="attendance-ai-dialog">
      <DialogHeader>
        <DialogTitle>AI 导入考勤</DialogTitle>
        <DialogDescription>
          支持上传已有考勤文档（截图/导出表/系统导出文件），AI 自动识别表头与数据并匹配员工花名册。
        </DialogDescription>
      </DialogHeader>

      <!-- Step1 上传 -->
      <div v-if="step === 'upload'" class="flex flex-col gap-3">
        <input
          ref="fileInput"
          type="file"
          class="hidden"
          accept=".xlsx,.xls,.csv,.pdf,.png,.jpg"
          data-testid="attendance-ai-file"
          @change="handleFileChange"
        />
        <button
          type="button"
          class="flex flex-col items-center gap-1 rounded-lg border border-dashed px-4 py-6 text-sm hover:bg-accent"
          data-testid="attendance-ai-pick"
          @click="pickFile"
        >
          <span class="font-medium">{{ selectedFile ? selectedFile.name : "点击选择考勤文档" }}</span>
          <span class="text-muted-foreground text-xs">支持 xlsx / xls / csv / pdf / png / jpg</span>
        </button>

        <!-- 历史批次回看 -->
        <div v-if="historyBatches.length" class="flex flex-col gap-1.5" data-testid="attendance-ai-history">
          <p class="text-muted-foreground text-xs font-medium">历史批次（最近 10 次）</p>
          <div
            v-for="item in historyBatches"
            :key="item.id"
            class="flex flex-wrap items-center gap-2 rounded-md border px-3 py-1.5 text-xs"
            :data-testid="`attendance-ai-history-item-${item.id}`"
          >
            <Badge :variant="item.status === 'failed' ? 'destructive' : 'secondary'">
              {{ ATTENDANCE_BATCH_STATUS_LABELS[item.status] ?? item.status }}
            </Badge>
            <span class="text-muted-foreground">{{ item.created_at?.slice(0, 16).replace("T", " ") ?? "--" }}</span>
            <span class="text-muted-foreground">
              新增 {{ item.new_count }} · 覆盖 {{ item.overwrite_count }}<template v-if="item.fail_count > 0"> · 失败 {{ item.fail_count }}</template>
            </span>
            <Button
              v-if="item.fail_count > 0"
              variant="link"
              size="sm"
              class="ml-auto h-auto p-0"
              :disabled="downloadingId !== null"
              :data-testid="`attendance-ai-failures-${item.id}`"
              @click="downloadFailures(item)"
            >
              {{ downloadingId === item.id ? "下载中…" : "下载失败明细" }}
            </Button>
          </div>
        </div>
      </div>

      <!-- Step2 解析进度 -->
      <div v-else-if="step === 'parsing'" class="flex flex-col items-center gap-2 py-6" data-testid="attendance-ai-parsing">
        <Badge v-if="progressStatus" :variant="progressStatus === 'failed' ? 'destructive' : 'secondary'" :data-testid="`attendance-ai-status-${progressStatus}`">
          {{ ATTENDANCE_BATCH_STATUS_LABELS[progressStatus] ?? progressStatus }}
        </Badge>
        <div class="text-muted-foreground text-sm">
          {{ progressStatus === "failed" ? "解析失败，原文档已留存，可重新解析" : "AI 解析中，请稍候…" }}
        </div>
      </div>

      <!-- Step3 解析预览 -->
      <div v-else-if="step === 'preview'" class="flex flex-col gap-3">
        <div class="text-sm">
          解析完成：已勾选 <span class="font-medium">{{ selectedRows.size }}</span> 行（未匹配员工/字段缺失行默认不勾选）
        </div>
        <div class="max-h-64 overflow-auto rounded-lg border" data-testid="attendance-ai-preview-table">
          <table class="w-full text-left text-xs">
            <thead class="text-muted-foreground bg-muted/50 sticky top-0">
              <tr>
                <th class="w-10 px-3 py-2 font-medium">导入</th>
                <th class="px-3 py-2 font-medium">行号</th>
                <th class="px-3 py-2 font-medium">工号</th>
                <th class="px-3 py-2 font-medium">姓名</th>
                <th class="px-3 py-2 font-medium">日期</th>
                <th class="px-3 py-2 font-medium">校验结果</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in batch?.row_results ?? []" :key="row.row_index" class="border-t">
                <td class="px-3 py-1.5">
                  <input
                    type="checkbox"
                    :checked="selectedRows.has(row.row_index)"
                    :disabled="!row.parseable"
                    :data-testid="`attendance-ai-row-check-${row.row_index}`"
                    @change="toggleRow(row.row_index)"
                  />
                </td>
                <td class="px-3 py-1.5">{{ row.row_index }}</td>
                <td class="px-3 py-1.5">{{ row.employee_no ?? "--" }}</td>
                <td class="px-3 py-1.5">{{ row.employee_name ?? "--" }}</td>
                <td class="px-3 py-1.5">{{ row.work_date ?? "--" }}</td>
                <td class="px-3 py-1.5" :class="row.parseable ? '' : 'text-destructive'">
                  {{ row.parseable ? "可导入" : row.error ?? "校验失败" }}
                </td>
              </tr>
              <tr v-if="!batch?.row_results?.length">
                <td colspan="6" class="text-muted-foreground px-3 py-4 text-center">无解析行</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Step4 导入反馈 -->
      <div v-else class="flex flex-col items-center gap-2 py-4" data-testid="attendance-ai-result">
        <div class="text-base font-medium">导入完成</div>
        <div class="text-muted-foreground text-sm">
          新增 <span class="text-foreground font-medium">{{ batch?.new_count ?? 0 }}</span> 条 · 覆盖
          <span class="text-foreground font-medium">{{ batch?.overwrite_count ?? 0 }}</span> 条 · 丢弃
          <span class="text-foreground font-medium">{{ batch?.discard_count ?? 0 }}</span> 条
        </div>
      </div>

      <DialogFooter>
        <template v-if="step === 'upload'">
          <Button variant="outline" @click="close">取消</Button>
          <Button :disabled="submitting || !selectedFile" data-testid="attendance-ai-upload" @click="startParse">
            {{ submitting ? "上传中…" : "上传并解析" }}
          </Button>
        </template>
        <template v-else-if="step === 'parsing'">
          <Button variant="outline" @click="close">关闭</Button>
          <Button
            v-if="progressStatus === 'failed'"
            :disabled="submitting"
            data-testid="attendance-ai-retry"
            @click="retryParse"
          >
            重新解析
          </Button>
        </template>
        <template v-else-if="step === 'preview'">
          <Button variant="outline" @click="close">取消</Button>
          <Button :disabled="submitting || !canConfirm" data-testid="attendance-ai-confirm" @click="confirmImport">
            {{ submitting ? "导入中…" : `确认导入（${selectedRows.size} 行）` }}
          </Button>
        </template>
        <template v-else>
          <Button data-testid="attendance-ai-done" @click="close">完成</Button>
        </template>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
