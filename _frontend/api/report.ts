/**
 * 报表域 API（admin /hr/admin/v1/reports/*）
 * overview/turnover/recruiting 统一真日期区间（整月口径）+ 组织子树下钻（org_id）；
 * comp-dist/performance 无参；attrition-risk 规则评分实时名单
 */
import { get, post } from "@/framework/api/client";
import type { ApiResponse } from "@/framework/api/types";

import type {
  AttritionRiskData,
  CompDistData,
  OverviewData,
  PerformanceData,
  RecruitingData,
  ReportAskData,
  TurnoverData,
} from "@/hr/types/report";

export interface ReportRangeParams {
  date_from?: string;
  date_to?: string;
  org_id?: string;
}

export function getReportOverview(params: ReportRangeParams & { months?: number }): Promise<ApiResponse<OverviewData>> {
  return get<ApiResponse<OverviewData>>("/hr/admin/v1/reports/overview", { params });
}

export function getReportTurnover(params: ReportRangeParams & { months?: number }): Promise<ApiResponse<TurnoverData>> {
  return get<ApiResponse<TurnoverData>>("/hr/admin/v1/reports/turnover", { params });
}

export function getReportRecruiting(params: ReportRangeParams): Promise<ApiResponse<RecruitingData>> {
  return get<ApiResponse<RecruitingData>>("/hr/admin/v1/reports/recruiting", { params });
}

export function getReportAttritionRisk(params: { org_id?: string; limit?: number }): Promise<ApiResponse<AttritionRiskData>> {
  return get<ApiResponse<AttritionRiskData>>("/hr/admin/v1/reports/attrition-risk", { params });
}

export function getReportCompDist(): Promise<ApiResponse<CompDistData>> {
  return get<ApiResponse<CompDistData>>("/hr/admin/v1/reports/comp-dist");
}

/** 报表 Excel 导出（六域；comp-dist 域需薪酬查看权限；写审计） */
export function exportReport(
  params: ReportRangeParams & { domain: string; months?: number },
): Promise<ApiResponse<{ filename: string; content_base64: string }>> {
  return get<ApiResponse<{ filename: string; content_base64: string }>>("/hr/admin/v1/reports/export", { params });
}

export function getReportPerformance(): Promise<ApiResponse<PerformanceData>> {
  return get<ApiResponse<PerformanceData>>("/hr/admin/v1/reports/performance");
}

/** NL 问数（白名单指标聚合；越界 400；薪酬域无权限时降级回答） */
export function askReport(question: string): Promise<ApiResponse<ReportAskData>> {
  return post<ApiResponse<ReportAskData>>("/hr/admin/v1/reports/ask", { question });
}
