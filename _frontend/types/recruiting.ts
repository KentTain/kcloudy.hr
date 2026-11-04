/**
 * 招聘域类型（对齐 server/python/src/hr/schemas/recruiting.py 与
 * requisition_service / candidate_service 状态常量）
 */

import type { BadgeVariants } from "@/components/ui/badge";

/* ── 招聘需求 ── */

export type RequisitionStatus = "draft" | "recruiting" | "partial" | "filled" | "closed";

export const REQUISITION_STATUS_LABELS: Record<RequisitionStatus, string> = {
  draft: "草稿",
  recruiting: "招聘中",
  partial: "部分到岗",
  filled: "已满编",
  closed: "已关闭",
};

export const REQUISITION_STATUS_VARIANTS: Record<RequisitionStatus, BadgeVariants> = {
  draft: "outline",
  recruiting: "default",
  partial: "secondary",
  filled: "default",
  closed: "destructive",
};

export type RequisitionPriority = "low" | "medium" | "high" | "urgent";

export const REQUISITION_PRIORITY_LABELS: Record<RequisitionPriority, string> = {
  low: "低",
  medium: "中",
  high: "高",
  urgent: "紧急",
};

export const REQUISITION_PRIORITY_VARIANTS: Record<RequisitionPriority, BadgeVariants> = {
  low: "outline",
  medium: "secondary",
  high: "default",
  urgent: "destructive",
};

export const REQUISITION_PRIORITY_OPTIONS = (
  Object.entries(REQUISITION_PRIORITY_LABELS) as [RequisitionPriority, string][]
).map(([value, label]) => ({ value, label }));

/** 渠道：internal 站内直投恒可选；外部三家按渠道管理凭证状态出项 */
export type RecruitingChannel = "internal" | "zhilian" | "job51" | "liepin";

export const CHANNEL_LABELS: Record<RecruitingChannel, string> = {
  internal: "站内直投",
  zhilian: "智联招聘",
  job51: "前程无忧",
  liepin: "猎聘",
};

export const INTERNAL_CHANNEL: RecruitingChannel = "internal";

/** 渠道管理页渠道卡（/channels；仅外部三家） */
export interface ChannelCard {
  channel: string;
  name: string;
  configured: boolean;
  enabled: boolean;
  sync_enabled: boolean;
  collected_total: number;
  last_sync_at: string | null;
}

export interface RequisitionPosting {
  id: string;
  channel: string;
  status: string;
  external_post_id: string | null;
  published_at: string | null;
}

export const POSTING_STATUS_LABELS: Record<string, string> = {
  publishing: "发布中",
  published: "已发布",
  offline: "已下线",
  failed: "发布失败",
};

export const POSTING_STATUS_VARIANTS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  publishing: "secondary",
  published: "default",
  offline: "outline",
  failed: "destructive",
};

export interface Requisition {
  id: string;
  req_no: string;
  title: string;
  org_id: string;
  position_id: string | null;
  headcount: number;
  job_level: string | null;
  salary_min: number | null;
  salary_max: number | null;
  priority: RequisitionPriority;
  status: RequisitionStatus;
  jd: string | null;
  filled_count: number;
  postings: RequisitionPosting[];
}

export interface RequisitionQuery {
  page: number;
  page_size: number;
  status?: RequisitionStatus;
  priority?: RequisitionPriority;
  org_id?: string;
  keyword?: string;
}

export interface RequisitionCreatePayload {
  title: string;
  org_id: string;
  position_id?: string;
  headcount: number;
  job_level?: string;
  salary_min?: number;
  salary_max?: number;
  priority: RequisitionPriority;
  jd?: string;
  /** 非空时创建后立即发布 */
  channels?: string[];
}

export interface RequisitionUpdatePayload {
  title?: string;
  org_id?: string;
  position_id?: string;
  headcount?: number;
  job_level?: string;
  salary_min?: number;
  salary_max?: number;
  priority?: RequisitionPriority;
  jd?: string;
}

/* ── 漏斗统计 ── */

export interface FunnelStat {
  stage: string;
  count: number;
}

export interface FunnelResponse {
  requisition_id: string | null;
  stats: FunnelStat[];
}

/* ── 投递（候选人 × 需求）── */

/** 漏斗十态（对齐 candidate_service._STAGE_TRANSITIONS） */
export type ApplicationStage =
  | "pending_screening"
  | "screening_passed"
  | "interviewing"
  | "pre_hire"
  | "offered"
  | "pre_onboard"
  | "onboarded"
  | "onboard_abandoned"
  | "rejected"
  | "withdrawn";

export const APPLICATION_STAGE_LABELS: Record<ApplicationStage, string> = {
  pending_screening: "待初筛",
  screening_passed: "初筛通过",
  interviewing: "面试中",
  pre_hire: "拟录用",
  offered: "已发Offer",
  pre_onboard: "待入职",
  onboarded: "已入职",
  onboard_abandoned: "放弃入职",
  rejected: "已淘汰",
  withdrawn: "已撤回",
};

/** 三段漏斗分组（结果态 rejected/withdrawn/onboard_abandoned 不入漏斗段） */
export const FUNNEL_SEGMENTS: { key: string; label: string; stages: ApplicationStage[] }[] = [
  { key: "screening", label: "初筛", stages: ["pending_screening", "screening_passed"] },
  { key: "interview", label: "面试", stages: ["interviewing"] },
  { key: "hire", label: "录用", stages: ["pre_hire", "offered", "pre_onboard", "onboarded"] },
];

/** 阶段流转状态机（与后端 _STAGE_TRANSITIONS 同源；前端仅作操作出项，后端强校验） */
export const STAGE_TRANSITIONS: Record<ApplicationStage, ApplicationStage[]> = {
  pending_screening: ["screening_passed", "rejected", "withdrawn"],
  screening_passed: ["interviewing", "rejected", "withdrawn"],
  interviewing: ["pre_hire", "rejected", "withdrawn"],
  pre_hire: ["offered", "rejected"],
  offered: ["pre_onboard", "rejected"],
  pre_onboard: ["onboarded", "onboard_abandoned"],
  onboarded: [],
  onboard_abandoned: [],
  rejected: [],
  withdrawn: [],
};

export const APPLICATION_STAGE_VARIANTS: Record<ApplicationStage, BadgeVariants> = {
  pending_screening: "outline",
  screening_passed: "outline",
  interviewing: "default",
  pre_hire: "secondary",
  offered: "secondary",
  pre_onboard: "secondary",
  onboarded: "default",
  onboard_abandoned: "destructive",
  rejected: "destructive",
  withdrawn: "destructive",
};

export interface Application {
  id: string;
  candidate_id: string;
  candidate_name: string | null;
  requisition_id: string;
  requisition_title: string | null;
  stage: ApplicationStage;
  stage_history: { stage: string; operator_id: string | null; operated_at: string; remark: string | null }[];
  match_score: number | null;
  apply_time: string;
  employee_id: string | null;
}

/* ── 候选人 ── */

/** 候选人渠道：站内/外部招聘渠道 + manual（手工录入） */
export const CANDIDATE_CHANNEL_LABELS: Record<string, string> = {
  ...CHANNEL_LABELS,
  manual: "手工录入",
};

export const CANDIDATE_CHANNEL_OPTIONS = Object.entries(CANDIDATE_CHANNEL_LABELS).map(
  ([value, label]) => ({ value, label }),
);

export interface Candidate {
  id: string;
  name: string;
  phone: string | null;
  email: string | null;
  source_channel: string | null;
  is_blacklist: boolean;
  /** AI 归一结构化简历（分区容错渲染：education/work_experience/skills/highlights） */
  profile: Record<string, unknown> | null;
  resume_file: string | null;
}

export interface CandidateDetail extends Candidate {
  applications: Application[];
}

export interface CandidateCreatePayload {
  name: string;
  phone?: string;
  email?: string;
  source_channel?: string;
  requisition_id?: string;
}

export interface CandidateQuery {
  page?: number;
  page_size?: number;
  stage?: string;
  channel?: string;
  requisition_id?: string;
  keyword?: string;
  include_blacklist?: boolean;
}

/* ── 面试 ── */

export type InterviewForm = "onsite" | "online" | "phone";

export const INTERVIEW_FORM_LABELS: Record<InterviewForm, string> = {
  onsite: "现场面试",
  online: "视频面试",
  phone: "电话面试",
};

export const INTERVIEW_FORM_OPTIONS = Object.entries(INTERVIEW_FORM_LABELS).map(
  ([value, label]) => ({ value, label }),
);

export interface InterviewCreatePayload {
  interviewer_id: string;
  scheduled_at: string;
  interview_form: InterviewForm;
}

export interface Interview {
  id: string;
  application_id: string;
  round: number;
  interviewer_id: string;
  scheduled_at: string;
  interview_form: string;
  result: string;
  feedback: string | null;
  ai_summary: string | null;
}

/* ── 面试日程（周视图聚合） ── */

/** 周视图日程卡（weekly 聚合展开：application → candidate/requisition，无 feedback/ai_summary） */
export interface InterviewDayItem {
  id: string;
  application_id: string;
  candidate_name: string;
  requisition_title: string;
  round: number;
  interviewer_id: string;
  scheduled_at: string;
  interview_form: string;
  result: string;
}

export interface WeeklyInterviews {
  start: string;
  /** 日期（YYYY-MM-DD）→ 当日面试列表（空日也出键） */
  days: Record<string, InterviewDayItem[]>;
}

export const INTERVIEW_RESULT_LABELS: Record<string, string> = {
  pending: "待面试",
  pass: "通过",
  fail: "未通过",
};

export const INTERVIEW_RESULT_VARIANTS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "secondary",
  pass: "default",
  fail: "destructive",
};

/* ── Offer ── */

export type OfferStatus = "draft" | "sent" | "accepted" | "rejected";

export const OFFER_STATUS_LABELS: Record<string, string> = {
  draft: "待发送",
  sent: "已发送",
  accepted: "已接受",
  rejected: "已拒绝",
};

export interface Offer {
  id: string;
  application_id: string;
  /** 定薪方案快照：item_code → 金额（元） */
  salary_snapshot: Record<string, number>;
  status: string;
  valid_until: string | null;
  sent_at: string | null;
}

export interface OfferCreatePayload {
  application_id: string;
  salary_snapshot: Record<string, number>;
  valid_until?: string;
}

/* ── 合并建议 ── */

export interface MergeSuggestion {
  candidate_id: string;
  name: string;
  phone: string | null;
  email: string | null;
  matched_by: "phone" | "email";
}

