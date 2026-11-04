/**
 * 薪酬域类型（薪酬项字典 / 职级薪带版本）
 *
 * 对齐后端 hr/schemas/salary.py（SalaryItem / SalaryBand 族 Schema）；职级
 * job_level 为自由文本（与员工建档/岗位表单一致，无独立职级清单接口）。
 */

import type { PageQuery } from "@/hr/types";

/* ── 薪酬项 ── */

/** 规则元数据（ext_data）：影响定薪带出与发薪试算 */
export interface SalaryItemExtData {
  taxable?: boolean;
  social_security_base?: boolean;
  monthly_fixed?: boolean;
  unit?: string;
}

export interface SalaryItem {
  id: string;
  code: string;
  name: string;
  category: string;
  ext_data: SalaryItemExtData | null;
  /** false=已停用（被定薪方案/发薪明细引用的项只可停用不可删除） */
  can_edit: boolean;
  sort: number;
}

export interface SalaryItemQuery extends PageQuery {
  category?: string;
  keyword?: string;
}

export interface SalaryItemCreatePayload {
  code: string;
  name: string;
  category: string;
  ext_data?: SalaryItemExtData;
  sort?: number;
}

export interface SalaryItemUpdatePayload {
  name?: string;
  category?: string;
  ext_data?: SalaryItemExtData;
  /** false=停用 */
  can_edit?: boolean;
  sort?: number;
}

/** 停用薪酬项是否可恢复编辑（can_edit=false 即停用态） */
export const SALARY_ITEM_DISABLED_LABEL = "已停用";

/** 规则标识文案（列表规则列展示顺序） */
export const SALARY_ITEM_RULE_LABELS: { key: keyof SalaryItemExtData; label: string }[] = [
  { key: "taxable", label: "计税" },
  { key: "social_security_base", label: "社保基数" },
  { key: "monthly_fixed", label: "月度固定" },
];

/* ── 职级薪带 ── */

export interface SalaryBand {
  id: string;
  job_level: string;
  /** 元/月 */
  min_salary: number;
  mid_salary: number;
  max_salary: number;
  effective_from: string;
  /** 空 = 当前生效版本 */
  effective_to: string | null;
}

export type BandEffectiveStatus = "active" | "history" | "upcoming";

export const BAND_EFFECTIVE_STATUS_LABELS: Record<BandEffectiveStatus, string> = {
  active: "当前生效",
  history: "历史版本",
  upcoming: "未生效",
};

export const BAND_EFFECTIVE_STATUS_VARIANTS: Record<
  BandEffectiveStatus,
  "default" | "secondary" | "outline"
> = {
  active: "default",
  history: "outline",
  upcoming: "secondary",
};

/** 行内版本状态判定（与后端 effective_status 筛选同口径：effective_to 空=当前生效） */
export function bandEffectiveStatus(band: SalaryBand, today = new Date()): BandEffectiveStatus {
  if (!band.effective_to) return "active";
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  if (band.effective_from > todayStr) return "upcoming";
  return "history";
}

export interface SalaryBandQuery extends PageQuery {
  job_level?: string;
  effective_status?: BandEffectiveStatus;
}

export interface SalaryBandCreatePayload {
  job_level: string;
  min_salary: number;
  mid_salary: number;
  max_salary: number;
  effective_from: string;
  effective_to?: string;
}

export interface SalaryBandUpdatePayload {
  min_salary?: number;
  mid_salary?: number;
  max_salary?: number;
  effective_from?: string;
  effective_to?: string;
}

/* ── 定薪调薪 ── */

/** 调薪原因：入职定薪 / 调薪 / 晋升调薪 / 绩效调薪 */
export const SALARY_PACKAGE_REASON_LABELS: Record<string, string> = {
  hire: "入职定薪",
  adjust: "调薪",
  promotion: "晋升调薪",
  perf: "绩效调薪",
};

export interface SalaryPackageItemInput {
  item_id: string;
  /** 元/月 */
  amount: number;
}

/** 调薪提交（一事一流水：按项逐行闭合旧区间 + 生成新区间） */
export interface SalaryPackageAdjustPayload {
  items: SalaryPackageItemInput[];
  reason: string;
  effective_from: string;
}

/* ── 发薪批次 ── */

export type PayrollRunStatus = "draft" | "confirmed" | "paid" | "cancelled";

export const PAYROLL_STATUS_LABELS: Record<PayrollRunStatus, string> = {
  draft: "草稿",
  confirmed: "已确认",
  paid: "已发放",
  cancelled: "已取消",
};

export const PAYROLL_STATUS_VARIANTS: Record<PayrollRunStatus, "default" | "secondary" | "outline" | "destructive"> = {
  draft: "secondary",
  confirmed: "default",
  paid: "outline",
  cancelled: "destructive",
};

export interface PayrollRun {
  id: string;
  /** YYYY-MM，租户唯一 */
  period: string;
  status: PayrollRunStatus;
  /** 元 */
  total_amount: number | null;
  employee_count: number | null;
  pay_date: string | null;
}

export interface PayrollRunQuery extends PageQuery {
  status?: PayrollRunStatus;
}

export interface PayrollEntry {
  id: string;
  run_id: string;
  employee_id: string;
  employee_no: string | null;
  employee_name: string | null;
  item_id: string;
  item_code: string;
  /** 元 */
  amount: number;
  note: string | null;
}

/** 明细人工修正（仅 draft 态；金额修改须填备注留痕） */
export interface PayrollEntryUpdatePayload {
  amount: number;
  note?: string;
}

