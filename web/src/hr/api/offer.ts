/**
 * Offer 域 api（admin 层 /hr/admin/v1：创建（定薪快照）/发送/接受/拒绝/入职转化；
 * 卡片操作经申请维度查询端点取 offer_id）
 */

import { get, post, put } from "@/framework/api/client";

import type { ApiResponse } from "@/framework/api/types";

import type { Offer, OfferCreatePayload } from "@/hr/types/recruiting";

/** 创建 Offer 单（薪酬方案快照；申请须为拟录用） */
export function createOffer(payload: OfferCreatePayload): Promise<ApiResponse<Offer>> {
  return post<ApiResponse<Offer>>("/hr/admin/v1/offers", payload);
}

/** 发送 Offer（申请流转至已发 Offer） */
export function sendOffer(offerId: string): Promise<ApiResponse<Offer>> {
  return put<ApiResponse<Offer>>(`/hr/admin/v1/offers/${offerId}/send`);
}

/** 申请维度查 Offer（卡片接受/拒绝/入职操作入口；未发返回 null） */
export function getApplicationOffer(applicationId: string): Promise<ApiResponse<Offer | null>> {
  return get<ApiResponse<Offer | null>>(`/hr/admin/v1/applications/${applicationId}/offer`);
}

/** 候选人接受 Offer（申请流转至待入职） */
export function acceptOffer(offerId: string): Promise<ApiResponse<Offer>> {
  return post<ApiResponse<Offer>>(`/hr/admin/v1/offers/${offerId}/accept`);
}

/** 候选人拒绝 Offer（申请淘汰） */
export function rejectOffer(offerId: string): Promise<ApiResponse<Offer>> {
  return post<ApiResponse<Offer>>(`/hr/admin/v1/offers/${offerId}/reject`);
}

export interface OfferOnboardPayload {
  hire_date?: string;
  position_id?: string;
}

/** 入职转化建档（员工自动取号 + hire 流水；需求 filled_count 联动） */
export function onboardOffer(
  offerId: string,
  payload: OfferOnboardPayload = {},
): Promise<ApiResponse<{ employee_id: string; employee_no: string }>> {
  return post<ApiResponse<{ employee_id: string; employee_no: string }>>(
    `/hr/admin/v1/offers/${offerId}/onboard`,
    payload,
  );
}
