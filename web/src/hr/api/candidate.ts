/**
 * 候选人域 api（admin 层 /hr/admin/v1：卡片流/主档 CRUD/黑名单/合并/AI 解析）
 */

import { del, get, post, put } from "@/framework/api/client";

import type { ApiResponse } from "@/framework/api/types";

import type {
  Application,
  Candidate,
  CandidateCreatePayload,
  CandidateDetail,
  CandidateQuery,
  MergeSuggestion,
} from "@/hr/types/recruiting";

/** 投递卡片流分页（黑名单默认隐藏；一行=一条投递申请聚合候选人主档） */
export function listCandidateCards(
  query: CandidateQuery = {},
): Promise<ApiResponse<Application[]>> {
  return get<ApiResponse<Application[]>>("/hr/admin/v1/candidates", { params: query });
}

/** 手工录入候选人（关联需求时同步产生待初筛投递） */
export function createCandidate(
  payload: CandidateCreatePayload,
): Promise<ApiResponse<Candidate & { application?: Application }>> {
  return post<ApiResponse<Candidate & { application?: Application }>>(
    "/hr/admin/v1/candidates",
    payload,
  );
}

/** 候选人详情（主档 + 全部投递申请） */
export function getCandidate(candidateId: string): Promise<ApiResponse<CandidateDetail>> {
  return get<ApiResponse<CandidateDetail>>(`/hr/admin/v1/candidates/${candidateId}`);
}

/** 编辑候选人主档 */
export function updateCandidate(
  candidateId: string,
  payload: { name?: string; phone?: string; email?: string },
): Promise<ApiResponse<Candidate>> {
  return put<ApiResponse<Candidate>>(`/hr/admin/v1/candidates/${candidateId}`, payload);
}

/** 删除候选人（存在进行中投递时后端拒绝） */
export function deleteCandidate(candidateId: string): Promise<ApiResponse<unknown>> {
  return del<ApiResponse<unknown>>(`/hr/admin/v1/candidates/${candidateId}`);
}

/** 触发 AI 简历解析任务（异步回写 profile，失败可重试） */
export function parseResume(candidateId: string): Promise<ApiResponse<{ candidate_id: string }>> {
  return post<ApiResponse<{ candidate_id: string }>>(
    `/hr/admin/v1/candidates/${candidateId}/resume/parse`,
  );
}

/** 重复档合并：source 投递/面试归并到 target 后删除 source（需 hr:candidate:merge） */
export function mergeCandidates(
  sourceId: string,
  targetId: string,
): Promise<ApiResponse<{ merged_applications: number }>> {
  return post<ApiResponse<{ merged_applications: number }>>(
    `/hr/admin/v1/candidates/${sourceId}/merge/${targetId}`,
  );
}

/** 疑似重复档建议（手机/邮箱命中；供合并弹窗直选目标） */
export function getMergeSuggestions(
  candidateId: string,
): Promise<ApiResponse<MergeSuggestion[]>> {
  return get<ApiResponse<MergeSuggestion[]>>(
    `/hr/admin/v1/candidates/${candidateId}/merge-suggestions`,
  );
}

/** 加入/移出黑名单（黑名单默认筛选不展示） */
export function setBlacklist(candidateId: string, blacklist: boolean): Promise<ApiResponse<Candidate>> {
  return post<ApiResponse<Candidate>>(
    `/hr/admin/v1/candidates/${candidateId}/${blacklist ? "blacklist" : "unblacklist"}`,
  );
}

/** 投递详情（含流转史与面试轮次数） */
export function getApplication(applicationId: string): Promise<ApiResponse<Application>> {
  return get<ApiResponse<Application>>(`/hr/admin/v1/applications/${applicationId}`);
}
