/**
 * 绩效域 API（admin 管理端）
 * 前缀 /hr/admin/v1：周期 CRUD/状态机推进/分布 + 目标整批提交/编辑/进度/删除
 * + 评估批量发起/评分/校准（批 C）
 */
import { del, get, post, put } from "@/framework/api/client";
import type { ApiResponse } from "@/framework/api/types";

import type {
  PerfCycleItem,
  PerfCycleQuery,
  PerfDistribution,
  PerfGoalDraftRow,
  PerfGoalItem,
  PerfGoalQuery,
  PerfReviewDraftRow,
  PerfReviewItem,
  PerfReviewQuery,
} from "@/hr/types/perf";

export function listPerfCycles(
  query: PerfCycleQuery,
): Promise<ApiResponse<PerfCycleItem[]>> {
  return get<ApiResponse<PerfCycleItem[]>>("/hr/admin/v1/perf-cycles", {
    params: query,
  });
}

export function getPerfCycle(id: string): Promise<ApiResponse<PerfCycleItem>> {
  return get<ApiResponse<PerfCycleItem>>(`/hr/admin/v1/perf-cycles/${id}`);
}

export function createPerfCycle(data: {
  name: string;
  start_date: string;
  end_date: string;
}): Promise<ApiResponse<PerfCycleItem>> {
  return post<ApiResponse<PerfCycleItem>>("/hr/admin/v1/perf-cycles", data);
}

export function updatePerfCycle(
  id: string,
  data: { name?: string; start_date?: string; end_date?: string },
): Promise<ApiResponse<PerfCycleItem>> {
  return put<ApiResponse<PerfCycleItem>>(`/hr/admin/v1/perf-cycles/${id}`, data);
}

export function deletePerfCycle(id: string): Promise<ApiResponse<null>> {
  return del<ApiResponse<null>>(`/hr/admin/v1/perf-cycles/${id}`);
}

export function transitionPerfCycle(
  id: string,
  action: "activate" | "scoring" | "calibrating" | "close",
): Promise<ApiResponse<PerfCycleItem>> {
  return post<ApiResponse<PerfCycleItem>>(`/hr/admin/v1/perf-cycles/${id}/${action}`, {});
}

export function getPerfDistribution(id: string): Promise<ApiResponse<PerfDistribution>> {
  return get<ApiResponse<PerfDistribution>>(`/hr/admin/v1/perf-cycles/${id}/distribution`);
}

export function listPerfGoals(
  query: PerfGoalQuery,
): Promise<ApiResponse<PerfGoalItem[]>> {
  return get<ApiResponse<PerfGoalItem[]>>("/hr/admin/v1/perf-goals", {
    params: query,
  });
}

export function submitPerfGoals(data: {
  cycle_id: string;
  employee_id: string;
  goals: PerfGoalDraftRow[];
}): Promise<ApiResponse<PerfGoalItem[]>> {
  return post<ApiResponse<PerfGoalItem[]>>("/hr/admin/v1/perf-goals", data);
}

export function updatePerfGoal(
  id: string,
  data: { name?: string; weight?: number; target_value?: string },
): Promise<ApiResponse<PerfGoalItem>> {
  return put<ApiResponse<PerfGoalItem>>(`/hr/admin/v1/perf-goals/${id}`, data);
}

export function updatePerfGoalProgress(
  id: string,
  data: { progress: number; actual_value?: string },
): Promise<ApiResponse<PerfGoalItem>> {
  return put<ApiResponse<PerfGoalItem>>(`/hr/admin/v1/perf-goals/${id}/progress`, data);
}

export function deletePerfGoal(id: string): Promise<ApiResponse<null>> {
  return del<ApiResponse<null>>(`/hr/admin/v1/perf-goals/${id}`);
}

export function listPerfReviews(
  query: PerfReviewQuery,
): Promise<ApiResponse<PerfReviewItem[]>> {
  return get<ApiResponse<PerfReviewItem[]>>("/hr/admin/v1/perf-reviews", {
    params: query,
  });
}

export function createPerfReviews(data: {
  cycle_id: string;
  items: { employee_id: string; reviewer_employee_id: string }[];
}): Promise<ApiResponse<{ cycle_id: string; created: number; skipped: number }>> {
  return post("/hr/admin/v1/perf-reviews", data);
}

export function scorePerfReview(
  id: string,
  data: { score: number; rating: string; self_score?: number },
): Promise<ApiResponse<PerfReviewItem>> {
  return put<ApiResponse<PerfReviewItem>>(`/hr/admin/v1/perf-reviews/${id}/score`, data);
}

export function calibratePerfReview(
  id: string,
  data: { rating: string; comment: string },
): Promise<ApiResponse<PerfReviewItem>> {
  return put<ApiResponse<PerfReviewItem>>(
    `/hr/admin/v1/perf-reviews/${id}/calibrate`,
    data,
  );
}
