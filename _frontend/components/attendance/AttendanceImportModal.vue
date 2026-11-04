<script setup lang="ts">
/**
 * Excel 导入弹窗：下载模板 + 上传 → dryRun 预检（逐行校验回显）→ 确认导入
 * （同员工同日覆盖更新）→ 批次反馈。预检失败行不落库，修正后重传。
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

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { getImportTemplate, importAttendance } from "@/hr/api/attendance";
import type { AttendanceImportResult } from "@/hr/types/attendance";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ "update:open": [value: boolean]; saved: [] }>();

type Step = "upload" | "preview" | "result";

const step = ref<Step>("upload");
const fileInput = ref<HTMLInputElement | null>(null);
const selectedFile = ref<File | null>(null);
const submitting = ref(false);
const previewResult = ref<AttendanceImportResult | null>(null);
const commitResult = ref<AttendanceImportResult | null>(null);

const failCount = computed(() => previewResult.value?.fail_count ?? 0);
const newCount = computed(() => commitResult.value?.new_count ?? 0);
const overwriteCount = computed(() => commitResult.value?.overwrite_count ?? 0);

watch(
  () => props.open,
  (open) => {
    if (open) resetState();
  },
);

function resetState() {
  step.value = "upload";
  selectedFile.value = null;
  previewResult.value = null;
  commitResult.value = null;
  submitting.value = false;
  if (fileInput.value) fileInput.value.value = "";
}

function pickFile() {
  fileInput.value?.click();
}

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement;
  selectedFile.value = input.files?.[0] ?? null;
}

async function downloadTemplate() {
  try {
    const res = await getImportTemplate();
    const data = res.data;
    if (!data?.content_base64) {
      notifyError(new Error("模板下载失败"));
      return;
    }
    const binary = atob(data.content_base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = data.filename || "考勤导入模板.xlsx";
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    notifyError(error, getErrorMessage(error, "模板下载失败"));
  }
}

async function startPreview() {
  if (!selectedFile.value) {
    notifyError(new Error("请先选择考勤文件"));
    return;
  }
  submitting.value = true;
  try {
    const res = await importAttendance(selectedFile.value, true);
    previewResult.value = res.data ?? null;
    step.value = "preview";
  } catch (error) {
    notifyError(error, getErrorMessage(error, "预检失败，请检查文件格式"));
  } finally {
    submitting.value = false;
  }
}

async function confirmImport() {
  if (!selectedFile.value || failCount.value > 0) return;
  submitting.value = true;
  try {
    const res = await importAttendance(selectedFile.value, false);
    commitResult.value = res.data ?? null;
    step.value = "result";
    notifySuccess(`导入完成：新增 ${commitResult.value?.new_count ?? 0} 条，覆盖 ${commitResult.value?.overwrite_count ?? 0} 条`);
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "导入失败"));
  } finally {
    submitting.value = false;
  }
}

function backToUpload() {
  step.value = "upload";
  previewResult.value = null;
  if (fileInput.value) fileInput.value.value = "";
}

function close() {
  emit("update:open", false);
}
</script>

<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-2xl" data-testid="attendance-import-dialog">
      <DialogHeader>
        <DialogTitle>Excel 导入考勤</DialogTitle>
        <DialogDescription>
          先下载模板填写，上传后系统预检（不落库）；同员工同日已存在记录按覆盖更新处理。
        </DialogDescription>
      </DialogHeader>

      <!-- Step1 上传 -->
      <div v-if="step === 'upload'" class="flex flex-col gap-3">
        <Button variant="outline" class="w-fit" data-testid="attendance-template-download" @click="downloadTemplate">
          下载导入模板
        </Button>
        <input
          ref="fileInput"
          type="file"
          class="hidden"
          accept=".xlsx,.xls,.csv"
          data-testid="attendance-import-file"
          @change="handleFileChange"
        />
        <button
          type="button"
          class="flex flex-col items-center gap-1 rounded-lg border border-dashed px-4 py-6 text-sm hover:bg-accent"
          data-testid="attendance-import-pick"
          @click="pickFile"
        >
          <span class="font-medium">{{ selectedFile ? selectedFile.name : "点击选择考勤文件" }}</span>
          <span class="text-muted-foreground text-xs">支持 xlsx / xls / csv</span>
        </button>
      </div>

      <!-- Step2 预检结果 -->
      <div v-else-if="step === 'preview'" class="flex flex-col gap-3">
        <div class="text-sm">
          预检完成：可导入 {{ previewResult?.row_results.filter((row) => row.parseable).length ?? 0 }} 行，失败
          <span class="text-destructive font-medium">{{ failCount }}</span> 行（失败行不落库）
        </div>
        <div class="max-h-64 overflow-auto rounded-lg border" data-testid="attendance-preview-table">
          <table class="w-full text-left text-xs">
            <thead class="text-muted-foreground bg-muted/50 sticky top-0">
              <tr>
                <th class="px-3 py-2 font-medium">行号</th>
                <th class="px-3 py-2 font-medium">工号</th>
                <th class="px-3 py-2 font-medium">姓名</th>
                <th class="px-3 py-2 font-medium">日期</th>
                <th class="px-3 py-2 font-medium">校验结果</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in previewResult?.row_results ?? []" :key="row.row_index" class="border-t">
                <td class="px-3 py-1.5">{{ row.row_index }}</td>
                <td class="px-3 py-1.5">{{ row.employee_no ?? "--" }}</td>
                <td class="px-3 py-1.5">{{ row.employee_name ?? "--" }}</td>
                <td class="px-3 py-1.5">{{ row.work_date ?? "--" }}</td>
                <td class="px-3 py-1.5" :class="row.parseable ? '' : 'text-destructive'">
                  {{ row.parseable ? "可导入" : row.error ?? "校验失败" }}
                </td>
              </tr>
              <tr v-if="!previewResult?.row_results?.length">
                <td colspan="5" class="text-muted-foreground px-3 py-4 text-center">无解析行</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Step3 导入反馈 -->
      <div v-else class="flex flex-col items-center gap-2 py-4" data-testid="attendance-import-result">
        <div class="text-base font-medium">导入完成</div>
        <div class="text-muted-foreground text-sm">
          新增 <span class="text-foreground font-medium">{{ newCount }}</span> 条 · 覆盖
          <span class="text-foreground font-medium">{{ overwriteCount }}</span> 条 · 失败
          <span class="text-foreground font-medium">{{ commitResult?.fail_count ?? 0 }}</span> 条
        </div>
      </div>

      <DialogFooter>
        <template v-if="step === 'upload'">
          <Button variant="outline" @click="close">取消</Button>
          <Button :disabled="submitting || !selectedFile" data-testid="attendance-import-preview" @click="startPreview">
            {{ submitting ? "预检中…" : "开始预检" }}
          </Button>
        </template>
        <template v-else-if="step === 'preview'">
          <Button variant="outline" data-testid="attendance-import-back" @click="backToUpload">上一步</Button>
          <Button :disabled="submitting || failCount > 0" data-testid="attendance-import-confirm" @click="confirmImport">
            {{ submitting ? "导入中…" : failCount > 0 ? "存在失败行，修正后重传" : "确认导入" }}
          </Button>
        </template>
        <template v-else>
          <Button data-testid="attendance-import-done" @click="close">完成</Button>
        </template>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
