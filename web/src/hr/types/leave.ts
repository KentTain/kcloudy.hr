/**
 * 假勤域类型（假期类型 / 假期余额 / 请假单）
 * 对应后端 hr/schemas/leave.py（LeaveType / LeaveBalance / LeaveRequest 族）
 */
import type { PageQuery } from "@/hr/types";

/* ── 假期类型 ── */

export type LeaveUnit = "day" | "hour";
export type LeaveQuotaRule = "annual_fixed" | "manual";
export type LeaveTypeStatus = "enabled" | "disabled";

export const LEAVE_UNIT_LABELS: Record<LeaveUnit, string> = {
  day: "天",
  hour: "小时",
};

export const LEAVE_QUOTA_RULE_LABELS: Record<LeaveQuotaRule, string> = {
  annual_fixed: "按年度固定额度",
  manual: "仅手工调整",
};

export const LEAVE_TYPE_STATUS_LABELS: Record<LeaveTypeStatus, string> = {
  enabled: "启用",
  disabled: "停用",
};

export const LEAVE_TYPE_STATUS_VARIANTS: Record<LeaveTypeStatus, "success" | "secondary"> = {
  enabled: "success",
  disabled: "secondary",
};

export interface LeaveType {
  id: string;
  code: string;
  name: string;
  unit: LeaveUnit;
  paid: boolean;
  quota_rule: LeaveQuotaRule;
  default_quota: number | null;
  status: LeaveTypeStatus;
}

export interface LeaveTypeQuery extends PageQuery {
  status?: LeaveTypeStatus;
}

export interface LeaveTypePayload {
  code?: string;
  name: string;
  unit: LeaveUnit;
  paid: boolean;
  quota_rule: LeaveQuotaRule;
  default_quota?: number | null;
  status?: LeaveTypeStatus;
}

/* ── 请假单 ── */

export type LeaveRequestStatus = "pending" | "approved" | "rejected" | "cancelled";

export const LEAVE_REQUEST_STATUS_LABELS: Record<LeaveRequestStatus, string> = {
  pending: "待审批",
  approved: "已通过",
  rejected: "已驳回",
  cancelled: "已撤销",
};

export const LEAVE_REQUEST_STATUS_VARIANTS: Record<
  LeaveRequestStatus,
  "default" | "success" | "destructive" | "secondary"
> = {
  pending: "default",
  approved: "success",
  rejected: "destructive",
  cancelled: "secondary",
};

export interface LeaveRequest {
  id: string;
  employee_id: string;
  employee_no: string | null;
  employee_name: string | null;
  org_id: string | null;
  leave_type_id: string;
  leave_type_code: string | null;
  leave_type_name: string | null;
  unit: LeaveUnit | null;
  start_time: string;
  end_time: string;
  duration: number;
  reason: string;
  attachment_file: string | null;
  status: LeaveRequestStatus;
  approver_id: string | null;
  approve_comment: string | null;
  approved_at: string | null;
  created_at: string | null;
}

export interface LeaveRequestQuery extends PageQuery {
  status?: LeaveRequestStatus;
  leave_type_id?: string;
  org_id?: string;
  keyword?: string;
  date_from?: string;
  date_to?: string;
}

export interface LeaveRequestCreatePayload {
  leave_type_id: string;
  start_time: string;
  end_time: string;
  reason: string;
  attachment_file?: string;
}

/* ── 假期余额 ── */

export interface LeaveBalance {
  id: string;
  employee_id: string;
  employee_no: string | null;
  employee_name: string | null;
  org_id: string | null;
  leave_type_id: string;
  leave_type_code: string | null;
  leave_type_name: string | null;
  unit: LeaveUnit | null;
  year: number;
  total_quota: number;
  used: number;
  frozen: number;
  balance: number;
}

export interface LeaveBalanceQuery extends PageQuery {
  year?: number;
  org_id?: string;
  keyword?: string;
  leave_type_id?: string;
}

/* ── 时长计算（展示口径，落库以后端为准） ── */

/** day = 起止日期闭区间天数；hour = 起止时间差小时数（不足一分钟向上取整到 0.01） */
export function computeLeaveDuration(unit: LeaveUnit, startTime: string, endTime: string): number | null {
  const start = new Date(startTime);
  const end = new Date(endTime);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end < start) return null;
  if (unit === "hour") {
    const hours = (end.getTime() - start.getTime()) / 3600000;
    return Math.round(hours * 100) / 100;
  }
  const startDate = new Date(start.getFullYear(), start.getMonth(), start.getDate());
  const endDate = new Date(end.getFullYear(), end.getMonth(), end.getDate());
  return Math.round((endDate.getTime() - startDate.getTime()) / 86400000) + 1;
}
