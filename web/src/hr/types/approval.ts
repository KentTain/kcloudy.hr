/**
 * 审批域类型（审批请求 / 审批流水）
 * 对应后端 hr/schemas/approval.py（ApprovalRequest / ApprovalAction 族）
 */
import type { PageQuery } from "@/hr/types";

/* ── 字典 ── */

export type ApprovalBizType = "profile_change";

export const APPROVAL_BIZ_TYPE_LABELS: Record<ApprovalBizType, string> = {
  profile_change: "档案变更申请",
};

export type ApprovalStatus = "pending" | "approved" | "rejected" | "cancelled";

export const APPROVAL_STATUS_LABELS: Record<ApprovalStatus, string> = {
  pending: "待审批",
  approved: "已通过",
  rejected: "已驳回",
  cancelled: "已撤销",
};

export const APPROVAL_STATUS_VARIANTS: Record<
  ApprovalStatus,
  "default" | "success" | "destructive" | "secondary"
> = {
  pending: "default",
  approved: "success",
  rejected: "destructive",
  cancelled: "secondary",
};

export type ApprovalActionType = "submit" | "approve" | "reject" | "cancel";

export const APPROVAL_ACTION_LABELS: Record<ApprovalActionType, string> = {
  submit: "提交",
  approve: "通过",
  reject: "驳回",
  cancel: "撤销",
};

/* ── 审批请求 ── */

export interface ApprovalActionItem {
  id: string;
  action: ApprovalActionType;
  actor_id: string | null;
  comment: string | null;
  created_at: string | null;
}

export interface ApprovalRequestItem {
  id: string;
  biz_type: ApprovalBizType;
  biz_ref_id: string | null;
  applicant_employee_id: string;
  employee_no: string | null;
  employee_name: string | null;
  org_id: string | null;
  applicant_user_id: string | null;
  title: string;
  payload: Record<string, unknown> | null;
  status: ApprovalStatus;
  approver_id: string | null;
  approve_comment: string | null;
  approved_at: string | null;
  created_at: string | null;
}

export interface ApprovalRequestDetail extends ApprovalRequestItem {
  actions: ApprovalActionItem[];
}

export interface ApprovalRequestQuery extends PageQuery {
  biz_type?: ApprovalBizType;
  status?: ApprovalStatus;
  applicant_employee_id?: string;
}

/** profile_change 载荷变更项 */
export interface ProfileChangeEntry {
  definition_id: string;
  new_value: unknown;
}
