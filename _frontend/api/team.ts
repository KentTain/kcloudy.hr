/**
 * 团队工作台 API（console /hr/console/v1/team/*：招聘/面试/待评分，数据按归属裁剪）
 */
import { get, put } from "@/framework/api/client";
import type { ApiResponse } from "@/framework/api/types";

import type { TeamInterviewItem, TeamRequisition, TeamReviewItem } from "@/hr/types/selfService";

/** 团队招聘需求（本人组织子树，分页） */
export function listTeamRequisitions(query: { page: number; page_size: number }): Promise<ApiResponse<TeamRequisition[]>> {
  return get<ApiResponse<TeamRequisition[]>>("/hr/console/v1/team/requisitions", { params: query });
}

/** 我参与的面试（时间倒序，无分页） */
export function listTeamInterviews(): Promise<ApiResponse<TeamInterviewItem[]>> {
  return get<ApiResponse<TeamInterviewItem[]>>("/hr/console/v1/team/interviews");
}

/** 待我评分的评估（scoring 态周期 + 未评分） */
export function listTeamReviews(): Promise<ApiResponse<TeamReviewItem[]>> {
  return get<ApiResponse<TeamReviewItem[]>>("/hr/console/v1/team/reviews");
}

/** 提交评分（reviewer 归属 + scoring 态双校验） */
export function submitTeamReviewScore(
  reviewId: string,
  data: { score: number; rating: string; self_score?: number | null },
): Promise<ApiResponse<{ id: string }>> {
  return put<ApiResponse<{ id: string }>>(`/hr/console/v1/team/reviews/${reviewId}/score`, data);
}
