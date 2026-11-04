/**
 * 面试域 api（admin 层 /hr/admin/v1：安排面试/周视图聚合/结论反馈改期/AI 纪要）
 */

import { get, post, put } from "@/framework/api/client";

import type { ApiResponse } from "@/framework/api/types";

import type { Interview, InterviewCreatePayload, WeeklyInterviews } from "@/hr/types/recruiting";

/** 安排面试（轮次自动 +1；不自动流转申请阶段，需另调 stage 流转） */
export function createInterview(
  applicationId: string,
  payload: InterviewCreatePayload,
): Promise<ApiResponse<Interview>> {
  return post<ApiResponse<Interview>>(
    `/hr/admin/v1/applications/${applicationId}/interviews`,
    payload,
  );
}

/** 周视图：起始于 start_date（YYYY-MM-DD，缺省今日）的 7 天面试按日分组 */
export function getWeeklyInterviews(startDate?: string): Promise<ApiResponse<WeeklyInterviews>> {
  return get<ApiResponse<WeeklyInterviews>>("/hr/admin/v1/interviews/weekly", {
    params: startDate ? { start_date: startDate } : {},
  });
}

/** 面试结论/反馈/改期（通过自动流转拟录用；改期通知面试官） */
export function updateInterview(
  interviewId: string,
  payload: { scheduled_at?: string; result?: string; feedback?: string },
): Promise<ApiResponse<Interview>> {
  return put<ApiResponse<Interview>>(`/hr/admin/v1/interviews/${interviewId}`, payload);
}

/** 面试详情（纪要任务提交后轮询 ai_summary 就绪） */
export function getInterviewDetail(interviewId: string): Promise<ApiResponse<Interview>> {
  return get<ApiResponse<Interview>>(`/hr/admin/v1/interviews/${interviewId}`);
}

/** 提交 AI 纪要任务（异步生成，消费者回写；进行中重复提交幂等返回既有 task_id） */
export function submitInterviewSummary(
  interviewId: string,
): Promise<ApiResponse<{ task_id: string; duplicated: boolean }>> {
  return post<ApiResponse<{ task_id: string; duplicated: boolean }>>(
    `/hr/admin/v1/interviews/${interviewId}/ai-summary`,
  );
}

/** 面试智能追问建议（即时生成不落库；失败走手动填写兜底） */
export function getFollowupQuestions(
  interviewId: string,
): Promise<ApiResponse<{ questions: string[] }>> {
  return post<ApiResponse<{ questions: string[] }>>(
    `/hr/admin/v1/interviews/${interviewId}/followup-questions`,
  );
}
