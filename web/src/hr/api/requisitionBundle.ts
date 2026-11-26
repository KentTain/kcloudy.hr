/**
 * 招聘聚合单 api（admin 层 /hr/admin/v1：流程测试载体，父子孙嵌套结构）
 */

import { get, post, put } from "@/framework/api/client";

import type { ApiResponse } from "@/framework/api/types";
import type {
  RequisitionBundleDetail,
  RequisitionBundleListItem,
  RequisitionBundlePayload,
} from "@/hr/types/recruiting";

/** 聚合单分页列表（需求行 + 申请数/Offer 数） */
export function listRequisitionBundles(
  query: { page: number; page_size: number; keyword?: string }
): Promise<ApiResponse<RequisitionBundleListItem[]>> {
  return get<ApiResponse<RequisitionBundleListItem[]>>("/hr/admin/v1/requisition-bundles", {
    params: query,
  });
}

/** 聚合单详情（父字段 + 申请明细行 + 行内 Offer） */
export function getRequisitionBundle(
  requisitionId: string
): Promise<ApiResponse<RequisitionBundleDetail>> {
  return get<ApiResponse<RequisitionBundleDetail>>(
    `/hr/admin/v1/requisition-bundles/${requisitionId}`
  );
}

/** 创建聚合单（需求 + 明细行 + 行内 Offer 三级一次落库） */
export function createRequisitionBundle(
  payload: RequisitionBundlePayload
): Promise<ApiResponse<RequisitionBundleDetail>> {
  return post<ApiResponse<RequisitionBundleDetail>>(
    "/hr/admin/v1/requisition-bundles",
    payload
  );
}

/** 编辑聚合单（父字段更新 + 明细按行 upsert） */
export function updateRequisitionBundle(
  requisitionId: string,
  payload: RequisitionBundlePayload
): Promise<ApiResponse<RequisitionBundleDetail>> {
  return put<ApiResponse<RequisitionBundleDetail>>(
    `/hr/admin/v1/requisition-bundles/${requisitionId}`,
    payload
  );
}
