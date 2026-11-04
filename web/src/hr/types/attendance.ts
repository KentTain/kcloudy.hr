/**
 * 考勤域类型（考勤记录 / 总览统计 / 导入批次）
 * 对应后端 hr/schemas/attendance.py（AttendanceRecord / AttendanceStats / 导入批次族）
 */
import type { PageQuery } from "@/hr/types";

/* ── 考勤记录 ── */

export type AttendanceStatus =
  | "normal"
  | "late"
  | "early_leave"
  | "late_early"
  | "absent"
  | "missing_card"
  | "leave"
  | "trip";

export type AttendanceSource = "excel" | "ai" | "leave";

export const ATTENDANCE_STATUS_LABELS: Record<AttendanceStatus, string> = {
  normal: "正常",
  late: "迟到",
  early_leave: "早退",
  late_early: "迟到且早退",
  absent: "缺勤",
  missing_card: "缺卡",
  leave: "请假",
  trip: "出差",
};

export const ATTENDANCE_STATUS_VARIANTS: Record<AttendanceStatus, "success" | "warning" | "destructive" | "secondary"> = {
  normal: "success",
  late: "warning",
  early_leave: "warning",
  late_early: "warning",
  absent: "destructive",
  missing_card: "warning",
  leave: "secondary",
  trip: "secondary",
};

export const ATTENDANCE_SOURCE_LABELS: Record<AttendanceSource, string> = {
  excel: "Excel 导入",
  ai: "AI 导入",
  leave: "请假",
};

export interface AttendanceRecord {
  id: string;
  employee_id: string;
  employee_no: string | null;
  employee_name: string | null;
  org_id: string | null;
  work_date: string;
  check_in_time: string | null;
  check_out_time: string | null;
  work_hours: number | null;
  overtime_hours: number | null;
  status: AttendanceStatus;
  source: AttendanceSource;
  remark: string | null;
}

export interface AttendanceQuery extends PageQuery {
  date_from?: string;
  date_to?: string;
  org_id?: string;
  keyword?: string;
  status?: AttendanceStatus;
}

/* ── 总览统计 ── */

export interface AttendanceStatsCards {
  total_records: number;
  attendance_count: number;
  late_count: number;
  early_leave_count: number;
  absent_count: number;
  attendance_rate: number | null;
}

export interface AttendanceOrgStat {
  org_id: string;
  total_records: number;
  attendance_count: number;
  late_count: number;
  early_leave_count: number;
  missing_card_count: number;
  absent_count: number;
  attendance_rate: number | null;
}

export interface AttendanceStats {
  cards: AttendanceStatsCards;
  org_slices: AttendanceOrgStat[];
}

/* ── 导入批次 ── */

export interface AttendanceRowResult {
  row_index: number;
  employee_no: string | null;
  employee_name: string | null;
  work_date: string | null;
  parseable: boolean;
  error: string | null;
  selected: boolean;
  data: Record<string, unknown> | null;
}

export type AttendanceBatchStatus = "pending" | "parsing" | "parsed" | "completed" | "failed";

export const ATTENDANCE_BATCH_STATUS_LABELS: Record<AttendanceBatchStatus, string> = {
  pending: "等待解析",
  parsing: "AI 解析中",
  parsed: "解析完成",
  completed: "已导入",
  failed: "解析失败",
};

export interface AttendanceBatch {
  id: string;
  channel: "excel" | "ai";
  status: AttendanceBatchStatus;
  file_id: string | null;
  filename: string | null;
  field_mapping: Record<string, unknown> | null;
  row_results: AttendanceRowResult[] | null;
  new_count: number;
  overwrite_count: number;
  discard_count: number;
  fail_count: number;
  created_at: string | null;
}

export interface AttendanceImportResult {
  batch_id: string;
  dry_run: boolean;
  row_results: AttendanceRowResult[];
  new_count: number;
  overwrite_count: number;
  fail_count: number;
}

/* ── 时间档位（固定五档，以当日为终点回溯） ── */

export const TIME_RANGE_OPTIONS = [
  { value: "1w", label: "近 1 周", days: 7 },
  { value: "1m", label: "近 1 月", days: 30 },
  { value: "1q", label: "近 1 季度", days: 90 },
  { value: "6m", label: "近半年", days: 180 },
  { value: "1y", label: "近 1 年", days: 365 },
] as const;

export type TimeRangeValue = (typeof TIME_RANGE_OPTIONS)[number]["value"];

function formatYmd(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** 时间档位映射为起止日期（date_to=当日，date_from=当日回溯 days-1 天） */
export function timeRangeToDates(
  value: TimeRangeValue,
  today = new Date(),
): { date_from: string; date_to: string } {
  const days = TIME_RANGE_OPTIONS.find((option) => option.value === value)?.days ?? 30;
  const from = new Date(today);
  from.setDate(from.getDate() - (days - 1));
  return { date_from: formatYmd(from), date_to: formatYmd(today) };
}

/* ── 打卡时间展示（datetime → HH:mm） ── */

export function formatCheckTime(value: string | null): string {
  if (!value) return "--";
  const time = value.length >= 16 ? value.slice(11, 16) : value;
  return time || "--";
}
