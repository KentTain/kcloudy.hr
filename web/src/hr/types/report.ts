/**
 * 报表域类型（/hr/admin/v1/reports/*）+ 真日期区间默认值
 */
import type { EmployeeStats } from "@/hr/types/employee";

/* ── 人事总览 ── */

export interface TrendPoint {
  month: string;
  count: number;
}

export interface OrgDistributionItem {
  org_id: string | null;
  count: number;
}

/* ── 指标口径引用（与 ontology 治理目录同源） ── */

export interface MetricRef {
  metric: string;
  display_name: string;
  description: string;
  source: "ontology" | "builtin";
}

export interface OverviewData {
  cards: EmployeeStats;
  headcount_trend: TrendPoint[];
  org_distribution: OrgDistributionItem[];
  metric_ref?: MetricRef | null;
}

export interface TurnoverPoint {
  month: string;
  offboarded: number;
  avg_headcount: number;
  rate: number | null;
}

export interface TurnoverData {
  points: TurnoverPoint[];
  metric_ref?: MetricRef | null;
}

/* ── 招聘漏斗与渠道 ── */

export interface FunnelStageCount {
  stage: string;
  count: number;
}

export interface ChannelStageCount {
  channel: string;
  stages: Record<string, number>;
}

export interface RecruitingData {
  funnel: FunnelStageCount[];
  channels: ChannelStageCount[];
}

/* ── 薪酬分布（脱敏，需 hr:salary_package:read） ── */

export interface CompDistItem {
  key: string | null;
  count: number;
  min_amount: number;
  mid_amount: number;
  max_amount: number;
}

export interface CompDistData {
  by_level: CompDistItem[];
  by_org: CompDistItem[];
}

/* ── 绩效分布（closed 周期） ── */

export interface CyclePerformance {
  cycle_id: string;
  cycle_name: string;
  end_date: string | null;
  total: number;
  avg_score: number | null;
  ratings: Record<string, number>;
}

export interface PerformanceData {
  cycles: CyclePerformance[];
  metric_ref?: MetricRef | null;
}

/* ── 离职风险名单（规则加权评分，实时计算） ── */

export interface AttritionRiskItem {
  employee_id: string;
  employee_no: string | null;
  name: string;
  org_id: string | null;
  score: number;
  level: "high" | "mid" | "low";
  factors: string[];
}

export interface AttritionRiskData {
  total: number;
  items: AttritionRiskItem[];
}

/* ── 报表区间（各域共用真日期区间，后端按整月口径展开） ── */

function formatDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** 默认报表区间：近 180 天回溯（含当日） */
export function defaultReportRange(today = new Date()): { date_from: string; date_to: string } {
  return {
    date_from: formatDate(new Date(today.getTime() - 179 * 86400000)),
    date_to: formatDate(today),
  };
}

/* ── NL 问数（白名单指标聚合口径） ── */

export interface ReportAskData {
  metric: string;
  domain: string;
  metric_ref: string;
  source: "keyword" | "llm";
  data: Record<string, unknown> | null;
  answer: string;
}
