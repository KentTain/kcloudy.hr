/**
 * 绩效域类型（考核周期 / 绩效目标 / 绩效评估 / 评级分布）
 * 对应后端 hr/schemas/perf.py（PerfCycle / PerfGoal / PerfReview / PerfDistribution 族）
 */
import type { PageQuery } from "@/hr/types";

/* ── 字典 ── */

export type PerfCycleStatus =
  | "draft"
  | "active"
  | "scoring"
  | "calibrating"
  | "closed";

export const PERF_CYCLE_STATUS_LABELS: Record<PerfCycleStatus, string> = {
  draft: "草稿",
  active: "进行中",
  scoring: "评分中",
  calibrating: "校准中",
  closed: "已收口",
};

export const PERF_CYCLE_STATUS_VARIANTS: Record<
  PerfCycleStatus,
  "default" | "success" | "destructive" | "secondary" | "outline"
> = {
  draft: "secondary",
  active: "success",
  scoring: "default",
  calibrating: "outline",
  closed: "destructive",
};

export type PerfGoalStatus = "open" | "completed";

export const PERF_GOAL_STATUS_LABELS: Record<PerfGoalStatus, string> = {
  open: "进行中",
  completed: "已完成",
};

export type PerfRating = "S" | "A" | "B" | "C" | "D";

export const PERF_RATINGS: PerfRating[] = ["S", "A", "B", "C", "D"];

export type PerfReviewStatus = "pending" | "submitted" | "calibrated";

export const PERF_REVIEW_STATUS_LABELS: Record<PerfReviewStatus, string> = {
  pending: "待评分",
  submitted: "已提交",
  calibrated: "已校准",
};

export const PERF_REVIEW_STATUS_VARIANTS: Record<
  PerfReviewStatus,
  "default" | "success" | "destructive" | "secondary" | "outline"
> = {
  pending: "secondary",
  submitted: "default",
  calibrated: "success",
};

/** 状态机推进动作：action → 按钮 label（源状态合法性后端 409 兜底） */
export const PERF_TRANSITION_LABELS: Record<string, string> = {
  activate: "激活",
  scoring: "进入评分",
  calibrating: "进入校准",
  close: "收口",
};

/** 每个状态可执行的推进动作 */
export const PERF_TRANSITIONS: Record<PerfCycleStatus, string[]> = {
  draft: ["activate"],
  active: ["scoring"],
  scoring: ["calibrating"],
  calibrating: ["close"],
  closed: [],
};

/* ── 考核周期 ── */

export interface PerfCycleItem {
  id: string;
  name: string;
  start_date: string;
  end_date: string;
  status: PerfCycleStatus;
  goal_count: number;
  review_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface PerfCycleQuery extends PageQuery {
  status?: PerfCycleStatus;
  date_from?: string;
  date_to?: string;
}

/* ── 绩效目标 ── */

export interface PerfGoalItem {
  id: string;
  cycle_id: string;
  employee_id: string;
  employee_no: string | null;
  employee_name: string | null;
  code: string;
  name: string;
  weight: number;
  target_value: string | null;
  actual_value: string | null;
  progress: number;
  status: PerfGoalStatus;
  created_at: string | null;
}

export interface PerfGoalQuery extends PageQuery {
  cycle_id?: string;
  employee_id?: string;
  status?: PerfGoalStatus;
}

/** 目标整批提交行 */
export interface PerfGoalDraftRow {
  code: string;
  name: string;
  weight: number;
  target_value: string;
}

/* ── 评级分布 ── */

export interface PerfRatingCount {
  count: number;
  percent: number;
}

export interface PerfDistribution {
  cycle_id: string;
  total: number;
  ratings: Record<PerfRating, PerfRatingCount>;
  /** 强制分布规则线（评级 → 占比上限 %，校准参考） */
  rules?: Record<string, number> | null;
}

/* ── 绩效评估 ── */

export interface PerfReviewItem {
  id: string;
  cycle_id: string;
  cycle_status: PerfCycleStatus | null;
  employee_id: string;
  employee_no: string | null;
  employee_name: string | null;
  reviewer_employee_id: string;
  reviewer_name: string | null;
  goal_count: number;
  weighted_progress: number;
  self_score: number | null;
  score: number | null;
  rating: PerfRating | null;
  calibrated_rating: PerfRating | null;
  calibration_comment: string | null;
  calibrated_at: string | null;
  coefficient: number | null;
  status: PerfReviewStatus;
  created_at: string | null;
}

export interface PerfReviewQuery extends PageQuery {
  cycle_id?: string;
  status?: PerfReviewStatus;
  reviewer_employee_id?: string;
}

/** 批量发起评估行（被评人 + 评估人） */
export interface PerfReviewDraftRow {
  employee_id: string;
  employee_label: string;
  reviewer_employee_id: string;
}
