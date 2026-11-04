/**
 * 考勤域 API（记录列表 / 总览统计 / Excel 与 AI 导入）
 * 后端 hr/controllers/admin/attendance_controller.py（前缀 /hr/admin/v1）
 */
import { get, post } from "@/framework/api/client";
import type { ApiResponse } from "@/framework/api/types";

import type {
  AttendanceBatch,
  AttendanceImportResult,
  AttendanceQuery,
  AttendanceRecord,
  AttendanceStats,
} from "@/hr/types/attendance";

export function listAttendanceRecords(
  query: AttendanceQuery,
): Promise<ApiResponse<AttendanceRecord[]>> {
  return get<ApiResponse<AttendanceRecord[]>>("/hr/admin/v1/attendance/records", { params: query });
}

export function getAttendanceStats(params: {
  date_from?: string;
  date_to?: string;
  org_id?: string;
  keyword?: string;
}): Promise<ApiResponse<AttendanceStats>> {
  return get<ApiResponse<AttendanceStats>>("/hr/admin/v1/attendance/stats", { params });
}

/** 下载 Excel 导入模板（base64 内容，调用方转 Blob 下载） */
export function getImportTemplate(): Promise<
  ApiResponse<{ filename: string; content_base64: string }>
> {
  return get<ApiResponse<{ filename: string; content_base64: string }>>(
    "/hr/admin/v1/attendance/import-template",
  );
}

/** Excel 导入（dry_run=true 预检不落库） */
export function importAttendance(
  file: File,
  dryRun: boolean,
): Promise<ApiResponse<AttendanceImportResult>> {
  const form = new FormData();
  form.append("file", file);
  form.append("dry_run", String(dryRun));
  return post<ApiResponse<AttendanceImportResult>>("/hr/admin/v1/attendance/import", form);
}

/** 上传考勤文档创建 AI 解析批次（临时区 + 异步解析任务） */
export function createAiImportBatch(file: File): Promise<ApiResponse<AttendanceBatch>> {
  const form = new FormData();
  form.append("file", file);
  return post<ApiResponse<AttendanceBatch>>("/hr/admin/v1/attendance/ai-imports", form);
}

export function getAiImportBatch(batchId: string): Promise<ApiResponse<AttendanceBatch>> {
  return get<ApiResponse<AttendanceBatch>>(`/hr/admin/v1/attendance/ai-imports/${batchId}`);
}

/** 确认导入（按勾选行落库，row_indexes 重复键多值） */
export function confirmAiImportBatch(
  batchId: string,
  rowIndexes: number[],
): Promise<ApiResponse<AttendanceBatch>> {
  const form = new FormData();
  for (const index of rowIndexes) {
    form.append("row_indexes", String(index));
  }
  return post<ApiResponse<AttendanceBatch>>(
    `/hr/admin/v1/attendance/ai-imports/${batchId}/confirm`,
    form,
  );
}

export function retryAiImportBatch(batchId: string): Promise<ApiResponse<AttendanceBatch>> {
  return post<ApiResponse<AttendanceBatch>>(
    `/hr/admin/v1/attendance/ai-imports/${batchId}/retry`,
  );
}

/** AI 导入批次列表（时间倒序，供导入弹窗回看历史批次） */
export function listAiImportBatches(
  params: { page?: number; page_size?: number } = {},
): Promise<ApiResponse<{ total: number; items: AttendanceBatch[] }>> {
  return get<ApiResponse<{ total: number; items: AttendanceBatch[] }>>(
    "/hr/admin/v1/attendance/ai-batches",
    { params },
  );
}

/** AI 批次失败行明细下载（xlsx，base64 内容，调用方转 Blob 下载） */
export function exportAiBatchFailures(
  batchId: string,
): Promise<ApiResponse<{ filename: string; content_base64: string }>> {
  return get<ApiResponse<{ filename: string; content_base64: string }>>(
    `/hr/admin/v1/attendance/ai-batches/${batchId}/failures`,
  );
}
