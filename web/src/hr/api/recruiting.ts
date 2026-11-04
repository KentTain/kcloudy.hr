/**
 * 招聘域 api（admin 层 /hr/admin/v1：需求 CRUD/发布/漏斗/投递/阶段流转）
 */

import { get, post, put } from "@/framework/api/client";

import type { ApiResponse } from "@/framework/api/types";

import type { Application, ApplicationStage } from "@/hr/types/recruiting";
import type {
  ChannelCard,
  FunnelResponse,
  Requisition,
  RequisitionCreatePayload,
  RequisitionQuery,
  RequisitionUpdatePayload,
} from "@/hr/types/recruiting";

/** 需求分页列表（含各渠道发布状态） */
export function listRequisitions(query: RequisitionQuery): Promise<ApiResponse<Requisition[]>> {
  return get<ApiResponse<Requisition[]>>("/hr/admin/v1/requisitions", { params: query });
}

/** 需求详情 */
export function getRequisition(requisitionId: string): Promise<ApiResponse<Requisition>> {
  return get<ApiResponse<Requisition>>(`/hr/admin/v1/requisitions/${requisitionId}`);
}

/** 创建需求（编号自动生成；channels 非空时创建后立即发布） */
export function createRequisition(
  payload: RequisitionCreatePayload,
): Promise<ApiResponse<Requisition>> {
  return post<ApiResponse<Requisition>>("/hr/admin/v1/requisitions", payload);
}

/** 更新需求（草稿/招聘中可编辑） */
export function updateRequisition(
  requisitionId: string,
  payload: RequisitionUpdatePayload,
): Promise<ApiResponse<Requisition>> {
  return put<ApiResponse<Requisition>>(`/hr/admin/v1/requisitions/${requisitionId}`, payload);
}

/** 关闭需求（人工终止；关闭后拒绝投递与流转） */
export function closeRequisition(requisitionId: string): Promise<ApiResponse<Requisition>> {
  return put<ApiResponse<Requisition>>(`/hr/admin/v1/requisitions/${requisitionId}/close`);
}

/** 发布需求到渠道（外部渠道任务化，回写 external_post_id） */
export function publishRequisition(
  requisitionId: string,
  channels: string[],
): Promise<ApiResponse<string[]>> {
  return post<ApiResponse<string[]>>(`/hr/admin/v1/requisitions/${requisitionId}/postings`, channels);
}

/** 下线已发布渠道职位 */
export function offlinePosting(postingId: string): Promise<ApiResponse<unknown>> {
  return put<ApiResponse<unknown>>(`/hr/admin/v1/postings/${postingId}/offline`);
}

/** 需求维度漏斗统计（各阶段人数） */
export function getRequisitionFunnel(requisitionId: string): Promise<ApiResponse<FunnelResponse>> {
  return get<ApiResponse<FunnelResponse>>(`/hr/admin/v1/requisitions/${requisitionId}/funnel`);
}

/** 全局漏斗统计（跨需求；需 hr:requisition:read，无权限时调用方降级空漏斗） */
export function getGlobalFunnel(): Promise<ApiResponse<FunnelResponse>> {
  return get<ApiResponse<FunnelResponse>>("/hr/admin/v1/recruiting/funnel");
}

/** 需求投递列表（候选人卡片流按需求筛选；需 hr:candidate:read） */
export function listRequisitionApplications(
  requisitionId: string,
  query: { page?: number; page_size?: number; stage?: ApplicationStage; keyword?: string } = {},
): Promise<ApiResponse<Application[]>> {
  return get<ApiResponse<Application[]>>("/hr/admin/v1/candidates", {
    params: { requisition_id: requisitionId, ...query },
  });
}

/** 投递阶段流转（状态机校验；onboarded 联动需求 filled_count） */
export function updateApplicationStage(
  applicationId: string,
  stage: ApplicationStage,
  remark?: string,
): Promise<ApiResponse<Application>> {
  return put<ApiResponse<Application>>(`/hr/admin/v1/applications/${applicationId}/stage`, {
    stage,
    remark,
  });
}

/** 渠道清单（渠道管理卡面；需 hr:channel:read，无权限时调用方降级静态渠道清单） */
export function listChannels(): Promise<ApiResponse<ChannelCard[]>> {
  return get<ApiResponse<ChannelCard[]>>("/hr/admin/v1/channels");
}

/** 手动触发渠道候选人拉取（任务化异步执行，返回任务 ID；需 hr:channel:sync） */
export function triggerChannelSync(channel: string): Promise<ApiResponse<{ task_id: string; channel: string }>> {
  return post<ApiResponse<{ task_id: string; channel: string }>>(`/hr/admin/v1/channels/${channel}/sync`);
}

/** 渠道连通测试：换 token 验证凭证（配置缺失/换取失败 ok=False；需 hr:channel:sync） */
export function testChannelConnection(
  channel: string,
): Promise<ApiResponse<{ channel: string; ok: boolean; message: string }>> {
  return post<ApiResponse<{ channel: string; ok: boolean; message: string }>>(
    `/hr/admin/v1/channels/${channel}/test-connection`,
  );
}

/** 渠道已发布职位与同步状态（需 hr:channel:read） */
export function listChannelPostings(channel: string): Promise<ApiResponse<RequisitionPosting[]>> {
  return get<ApiResponse<RequisitionPosting[]>>(`/hr/admin/v1/channels/${channel}/postings`);
}

/** JD 智能草稿生成（即时返回不落库；失败走手动编辑兜底） */
export function generateJdDraft(
  requisitionId: string,
): Promise<ApiResponse<{ jd_draft: string }>> {
  return post<ApiResponse<{ jd_draft: string }>>(
    `/hr/admin/v1/requisitions/${requisitionId}/jd-draft`,
  );
}
