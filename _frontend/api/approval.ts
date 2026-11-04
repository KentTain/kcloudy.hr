/**
 * 审批域 API（admin 管理端）
 * 前缀 /hr/admin/v1：审批请求列表 / 详情 / 通过 / 驳回
 * 提交入口在 console 员工自助（biz_type=profile_change），管理端仅审批处理。
 */
import { get, post } from "@/framework/api/client";
import type { ApiResponse } from "@/framework/api/types";

import type {
  ApprovalRequestDetail,
  ApprovalRequestItem,
  ApprovalRequestQuery,
} from "@/hr/types/approval";

export function listApprovalRequests(
  query: ApprovalRequestQuery
): Promise<ApiResponse<ApprovalRequestItem[]>> {
  return get<ApiResponse<ApprovalRequestItem[]>>("/hr/admin/v1/approval-requests", {
    params: query,
  });
}

export function getApprovalRequest(id: string): Promise<ApiResponse<ApprovalRequestDetail>> {
  return get<ApiResponse<ApprovalRequestDetail>>(`/hr/admin/v1/approval-requests/${id}`);
}

export function approveApprovalRequest(
  id: string,
  comment?: string
): Promise<ApiResponse<ApprovalRequestItem>> {
  return post<ApiResponse<ApprovalRequestItem>>(
    `/hr/admin/v1/approval-requests/${id}/approve`,
    comment ? { approve_comment: comment } : {}
  );
}

export function rejectApprovalRequest(
  id: string,
  comment: string
): Promise<ApiResponse<ApprovalRequestItem>> {
  return post<ApiResponse<ApprovalRequestItem>>(`/hr/admin/v1/approval-requests/${id}/reject`, {
    approve_comment: comment,
  });
}

/** 移交审批请求业务归属人（owner_id 可变归属；目标须同租户在册） */
export function transferApprovalRequest(
  id: string,
  ownerId: string
): Promise<ApiResponse<ApprovalRequestItem>> {
  return post<ApiResponse<ApprovalRequestItem>>(`/hr/admin/v1/approval-requests/${id}/transfer`, {
    owner_id: ownerId,
  });
}
