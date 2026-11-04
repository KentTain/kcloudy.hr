<script setup lang="ts">
/**
 * 员工批量导入弹窗：模板下载（CSV）→ 上传解析 → dryRun 预检（逐行错误回显）→ 确认导入。
 * 后端导入接口消费 JSON 行数据，文件解析在前端完成（当前支持 CSV）。
 */
import { ref } from "vue";

import { Button } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components";
import { FileDropzone } from "@/components";
import { Badge } from "@/components";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { importEmployees } from "@/hr/api/employee";
import type { EmployeeImportResult, EmployeeImportRowPayload } from "@/hr/types/employee";
import { parseCsv } from "@/hr/utils/csv";

const open = defineModel<boolean>("open", { required: true });

const emit = defineEmits<{ imported: [] }>();

const TEMPLATE_HEADERS = [
  "姓名",
  "性别",
  "出生日期",
  "证件号",
  "手机号",
  "工作邮箱",
  "组织ID",
  "岗位ID",
  "职级",
  "入职日期",
  "状态",
];

const rows = ref<EmployeeImportRowPayload[]>([]);
const result = ref<EmployeeImportResult | null>(null);
const parsing = ref(false);
const importing = ref(false);

function downloadTemplate() {
  const csv = `﻿${TEMPLATE_HEADERS.join(",")}\n张三,male,1995-01-01,110101199501011234,13800000001,zhangsan@company.com,,,,2026-11-01,pending\n`;
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "员工导入模板.csv";
  anchor.click();
  URL.revokeObjectURL(url);
}

function pick(row: Record<string, string>, key: string): string | undefined {
  const value = row[key]?.trim();
  return value ? value : undefined;
}

async function onFileSelect(files: File[]) {
  const file = files[0];
  if (!file) return;
  parsing.value = true;
  result.value = null;
  rows.value = [];
  try {
    const text = await file.text();
    const table = parseCsv(text);
    if (!table.length) {
      notifyError(new Error("文件为空"));
      return;
    }
    const headers = table[0].map((header) => header.trim());
    rows.value = table.slice(1).map((cells) => {
      const row: Record<string, string> = {};
      headers.forEach((header, index) => {
        row[header] = cells[index] ?? "";
      });
      return {
        name: row["姓名"]?.trim() ?? "",
        gender: pick(row, "性别"),
        birth_date: pick(row, "出生日期"),
        id_card: pick(row, "证件号"),
        phone: pick(row, "手机号"),
        work_email: pick(row, "工作邮箱"),
        org_id: pick(row, "组织ID"),
        position_id: pick(row, "岗位ID"),
        job_level: pick(row, "职级"),
        hire_date: row["入职日期"]?.trim() ?? "",
        status: (pick(row, "状态") as EmployeeImportRowPayload["status"]) ?? "pending",
      };
    });
    notifySuccess(`已解析 ${rows.value.length} 行数据`);
  } catch (error) {
    notifyError(error, getErrorMessage(error, "文件解析失败"));
  } finally {
    parsing.value = false;
  }
}

async function handleDryRun() {
  if (!rows.value.length) {
    notifyError(new Error("请先上传并解析文件"));
    return;
  }
  importing.value = true;
  try {
    const res = await importEmployees({ dry_run: true, rows: rows.value });
    result.value = res.data ?? null;
  } catch (error) {
    notifyError(error, getErrorMessage(error, "预检失败"));
  } finally {
    importing.value = false;
  }
}

async function handleImport() {
  importing.value = true;
  try {
    const res = await importEmployees({ dry_run: false, rows: rows.value });
    result.value = res.data ?? null;
    if ((res.data?.success_count ?? 0) > 0) {
      notifySuccess(`导入成功 ${res.data?.success_count} 条`);
      emit("imported");
    }
  } catch (error) {
    notifyError(error, getErrorMessage(error, "导入失败"));
  } finally {
    importing.value = false;
  }
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="flex max-h-[84vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-3xl" data-testid="employee-import-modal">
      <DialogHeader class="shrink-0 border-b px-6 py-4">
        <DialogTitle>批量导入员工</DialogTitle>
        <DialogDescription>
          下载模板填写后上传（CSV），先预检再导入；预检失败行不落库。
        </DialogDescription>
      </DialogHeader>

      <div class="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-6 py-4">
        <div class="flex items-center gap-3">
          <Button variant="outline" size="sm" data-testid="import-template-download" @click="downloadTemplate">
            下载导入模板
          </Button>
          <FileDropzone compact :accept="['.csv', 'text/csv']" data-testid="import-file-dropzone" @select="onFileSelect">
            <template #trigger="{ open: openPicker }">
              <Button variant="outline" size="sm" :disabled="parsing" @click="openPicker">
                {{ parsing ? "解析中…" : "选择 CSV 文件" }}
              </Button>
            </template>
          </FileDropzone>
          <Badge v-if="rows.length" variant="secondary" data-testid="import-row-count">
            已解析 {{ rows.length }} 行
          </Badge>
        </div>

        <div v-if="result" class="flex flex-col gap-2">
          <div class="flex items-center gap-3 text-sm" data-testid="import-result-summary">
            <Badge variant="secondary">共 {{ result.total }} 条</Badge>
            <Badge variant="default">成功 {{ result.success_count }}</Badge>
            <Badge variant="destructive">失败 {{ result.failure_count }}</Badge>
            <span v-if="result.dry_run" class="text-muted-foreground text-xs">（预检结果，未落库）</span>
          </div>
          <div class="max-h-56 overflow-y-auto rounded-md border">
            <table class="w-full text-sm">
              <thead class="bg-muted/50 sticky top-0">
                <tr>
                  <th class="px-3 py-2 text-left">行号</th>
                  <th class="px-3 py-2 text-left">结果</th>
                  <th class="px-3 py-2 text-left">工号</th>
                  <th class="px-3 py-2 text-left">错误原因</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in result.rows" :key="row.row_index" class="border-t">
                  <td class="px-3 py-1.5">{{ row.row_index + 1 }}</td>
                  <td class="px-3 py-1.5">
                    <Badge :variant="row.success ? 'default' : 'destructive'">
                      {{ row.success ? "成功" : "失败" }}
                    </Badge>
                  </td>
                  <td class="px-3 py-1.5">{{ row.employee_no ?? "--" }}</td>
                  <td class="px-3 py-1.5">{{ row.error ?? "--" }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <DialogFooter class="m-0 shrink-0 border-t px-6 py-3">
        <Button variant="outline" :disabled="importing || !rows.length" data-testid="import-dry-run" @click="handleDryRun">
          预检
        </Button>
        <Button :disabled="importing || !rows.length" data-testid="import-confirm" @click="handleImport">
          确认导入
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
