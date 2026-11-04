/**
 * 员工自助（console /hr/console/v1/me/* 与 /team/*）类型
 */
import type { AttributeValueItem, Employee, EmployeeDetail } from "@/hr/types/employee";
import type { PerfCycleStatus, PerfGoalStatus, PerfRating, PerfReviewStatus } from "@/hr/types/perf";
import type { Requisition } from "@/hr/types/recruiting";

export interface MyProfileData {
  profile: EmployeeDetail;
  attributes: AttributeValueItem[];
}

export interface PaySlipSummary {
  period: string;
  pay_date: string;
  item_count: number;
  total_amount: number;
}

export interface PaySlipItem {
  item_code: string;
  amount: number;
  note: string | null;
}

export interface PaySlipDetail {
  period: string;
  pay_date: string;
  total_amount: number;
  items: PaySlipItem[];
}

export type TeamEmployee = Employee;

/* ── 我的目标 ── */

export interface MyGoalItem {
  id: string;
  code: string;
  name: string;
  weight: number;
  target_value: string | null;
  actual_value: string | null;
  progress: number;
  status: PerfGoalStatus;
}

export interface MyGoalGroup {
  cycle_id: string;
  cycle_name: string;
  cycle_status: PerfCycleStatus;
  start_date: string;
  end_date: string;
  goals: MyGoalItem[];
}

/* ── 我的绩效 ── */

export interface MyReviewItem {
  id: string;
  cycle_id: string;
  cycle_name: string;
  cycle_status: PerfCycleStatus;
  status: PerfReviewStatus;
  self_score: number | null;
  score: number | null;
  rating: PerfRating | null;
  final_rating: PerfRating | null;
  /** 未收口周期为 null */
  coefficient: number | null;
}

/* ── 档案变更申请 ── */

export interface ChangeRequestDraftItem {
  definition_id: string;
  new_value: string | number | boolean | null;
}

export interface ChangeRequestSummary {
  id: string;
  biz_type: string;
  title: string;
  status: "pending" | "approved" | "rejected" | "cancelled";
  created_at: string | null;
  approver_id: string | null;
  approve_comment: string | null;
}

/* ── 团队工作台 ── */

export type TeamRequisition = Requisition;

export interface TeamInterviewItem {
  id: string;
  round: number;
  scheduled_at: string;
  interview_form: string;
  result: string;
  candidate_name: string;
  requisition_id: string;
  requisition_title: string;
}

export interface TeamReviewItem {
  id: string;
  cycle_id: string;
  cycle_name: string;
  employee_no: string | null;
  employee_name: string | null;
  goal_count: number;
  weighted_progress: number;
  self_score: number | null;
}
