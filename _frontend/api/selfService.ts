/**
 * 员工自助 API（console /hr/console/v1：本人档案/薪酬单/目标/绩效/变更申请 + 经理团队成员）
 */
import { get, post, put } from "@/framework/api/client";
import type { ApiResponse } from "@/framework/api/types";

import type {
  ChangeRequestDraftItem,
  ChangeRequestSummary,
  MyGoalGroup,
  MyProfileData,
  MyReviewItem,
  PaySlipDetail,
  PaySlipSummary,
  TeamEmployee,
} from "@/hr/types/selfService";

/** 本人档案（未关联员工时后端 404，调用方降级空态） */
export function getMyProfile(): Promise<ApiResponse<MyProfileData>> {
  return get<ApiResponse<MyProfileData>>("/hr/console/v1/me/profile");
}

/** 我的薪酬单（仅已发放批次，期间倒序，无分页） */
export function listMyPaySlips(): Promise<ApiResponse<PaySlipSummary[]>> {
  return get<ApiResponse<PaySlipSummary[]>>("/hr/console/v1/me/pay-slips");
}

export function getMyPaySlip(period: string): Promise<ApiResponse<PaySlipDetail>> {
  return get<ApiResponse<PaySlipDetail>>(`/hr/console/v1/me/pay-slips/${period}`);
}

/** 团队成员（本人组织子树，不含已离职），信封含 total 分页 */
export function listTeamEmployees(query: { page: number; page_size: number }): Promise<ApiResponse<TeamEmployee[]>> {
  return get<ApiResponse<TeamEmployee[]>>("/hr/console/v1/team/employees", { params: query });
}

/** 我的目标（按周期分组，进行中周期在前） */
export function getMyGoals(): Promise<ApiResponse<MyGoalGroup[]>> {
  return get<ApiResponse<MyGoalGroup[]>>("/hr/console/v1/me/goals");
}

/** 更新本人目标进度（仅 active 周期） */
export function updateMyGoalProgress(
  goalId: string,
  data: { progress: number; actual_value?: string | null },
): Promise<ApiResponse<{ id: string; progress: number; actual_value: string | null }>> {
  return put<ApiResponse<{ id: string; progress: number; actual_value: string | null }>>(
    `/hr/console/v1/me/goals/${goalId}/progress`,
    data,
  );
}

/** 我的绩效（历次评估结果，未收口周期无系数） */
export function getMyReviews(): Promise<ApiResponse<MyReviewItem[]>> {
  return get<ApiResponse<MyReviewItem[]>>("/hr/console/v1/me/reviews");
}

/** 我的档案变更申请列表 */
export function listMyChangeRequests(query: { page: number; page_size: number }): Promise<ApiResponse<ChangeRequestSummary[]>> {
  return get<ApiResponse<ChangeRequestSummary[]>>("/hr/console/v1/me/profile/change-requests", { params: query });
}

/** 提交档案变更申请（仅 self_editable 属性，走统一审批流） */
export function submitChangeRequest(data: {
  title: string;
  changes: ChangeRequestDraftItem[];
}): Promise<ApiResponse<{ id: string; status: string }>> {
  return post<ApiResponse<{ id: string; status: string }>>("/hr/console/v1/me/profile/change-requests", data);
}

/** 撤销待审批的变更申请（仅本人 pending） */
export function cancelChangeRequest(requestId: string): Promise<ApiResponse<{ id: string; status: string }>> {
  return post<ApiResponse<{ id: string; status: string }>>(
    `/hr/console/v1/me/profile/change-requests/${requestId}/cancel`,
  );
}
