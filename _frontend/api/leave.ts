/**
 * 假勤域 API（admin 管理端 + console 我的假期）
 * admin 前缀 /hr/admin/v1：假期类型 / 请假单审批 / 假期余额
 * console 前缀 /hr/console/v1：/me/leave-*（登录用户本人）
 */
import { del, get, post, put } from "@/framework/api/client";
import type { ApiResponse } from "@/framework/api/types";

import type {
  LeaveBalance,
  LeaveBalanceQuery,
  LeaveRequest,
  LeaveRequestCreatePayload,
  LeaveRequestQuery,
  LeaveRequestStatus,
  LeaveType,
  LeaveTypePayload,
  LeaveTypeQuery,
} from "@/hr/types/leave";

/* ── 假期类型（admin） ── */

export function listLeaveTypes(query: LeaveTypeQuery): Promise<ApiResponse<LeaveType[]>> {
  return get<ApiResponse<LeaveType[]>>("/hr/admin/v1/leave/types", { params: query });
}

export function createLeaveType(payload: LeaveTypePayload): Promise<ApiResponse<LeaveType>> {
  return post<ApiResponse<LeaveType>>("/hr/admin/v1/leave/types", payload);
}

/** 更新（后端 LeaveTypeUpdate 全字段可选，支持部分更新；编码不可改） */
export function updateLeaveType(
  id: string,
  payload: Partial<Omit<LeaveTypePayload, "code">>
): Promise<ApiResponse<LeaveType>> {
  return put<ApiResponse<LeaveType>>(`/hr/admin/v1/leave/types/${id}`, payload);
}

export function deleteLeaveType(id: string): Promise<ApiResponse<null>> {
  return del<ApiResponse<null>>(`/hr/admin/v1/leave/types/${id}`);
}

/* ── 请假单（admin） ── */

export function listLeaveRequests(query: LeaveRequestQuery): Promise<ApiResponse<LeaveRequest[]>> {
  return get<ApiResponse<LeaveRequest[]>>("/hr/admin/v1/leave/requests", { params: query });
}

export function approveLeaveRequest(id: string): Promise<ApiResponse<LeaveRequest>> {
  return post<ApiResponse<LeaveRequest>>(`/hr/admin/v1/leave/requests/${id}/approve`, {});
}

export function rejectLeaveRequest(
  id: string,
  comment: string
): Promise<ApiResponse<LeaveRequest>> {
  return post<ApiResponse<LeaveRequest>>(`/hr/admin/v1/leave/requests/${id}/reject`, {
    approve_comment: comment,
  });
}

/** 移交请假单业务归属人（owner_id 可变归属；目标须同租户在册） */
export function transferLeaveRequest(
  id: string,
  ownerId: string
): Promise<ApiResponse<LeaveRequest>> {
  return post<ApiResponse<LeaveRequest>>(`/hr/admin/v1/leave/requests/${id}/transfer`, {
    owner_id: ownerId,
  });
}

/* ── 假期余额（admin） ── */

export function listLeaveBalances(query: LeaveBalanceQuery): Promise<ApiResponse<LeaveBalance[]>> {
  return get<ApiResponse<LeaveBalance[]>>("/hr/admin/v1/leave/balances", { params: query });
}

export function adjustLeaveBalance(
  id: string,
  totalQuota: number
): Promise<ApiResponse<LeaveBalance>> {
  return put<ApiResponse<LeaveBalance>>(`/hr/admin/v1/leave/balances/${id}`, {
    total_quota: totalQuota,
  });
}

/* ── 我的假期（console） ── */

export function listMyLeaveBalances(year?: number): Promise<ApiResponse<LeaveBalance[]>> {
  return get<ApiResponse<LeaveBalance[]>>("/hr/console/v1/me/leave-balances", {
    params: year ? { year } : {},
  });
}

export function listMyLeaveRequests(params: {
  status?: LeaveRequestStatus;
  page: number;
  page_size: number;
}): Promise<ApiResponse<LeaveRequest[]>> {
  return get<ApiResponse<LeaveRequest[]>>("/hr/console/v1/me/leave-requests", { params });
}

export function submitMyLeaveRequest(
  payload: LeaveRequestCreatePayload
): Promise<ApiResponse<LeaveRequest>> {
  return post<ApiResponse<LeaveRequest>>("/hr/console/v1/me/leave-requests", payload);
}

export function cancelMyLeaveRequest(id: string): Promise<ApiResponse<LeaveRequest>> {
  return post<ApiResponse<LeaveRequest>>(`/hr/console/v1/me/leave-requests/${id}/cancel`, {});
}
