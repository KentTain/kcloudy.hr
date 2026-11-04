/**
 * 岗位域类型（对齐 server/python/src/hr/schemas/position.py）
 */

import type { BadgeVariants } from "@/components/ui/badge";

export type PositionStatus = "draft" | "active" | "disabled";

export const POSITION_STATUS_LABELS: Record<PositionStatus, string> = {
  draft: "草稿",
  active: "生效",
  disabled: "停用",
};

export const POSITION_STATUS_VARIANTS: Record<PositionStatus, BadgeVariants> = {
  draft: "outline",
  active: "default",
  disabled: "secondary",
};

export interface Position {
  id: string;
  code: string;
  name: string;
  org_id: string | null;
  job_level: string | null;
  headcount: number | null;
  /** 在岗人数实时统计（status ≠ offboarded 员工数，非落库字段） */
  active_employee_count: number;
  status: PositionStatus;
}

export interface PositionQuery {
  page: number;
  page_size: number;
  keyword?: string;
  org_id?: string;
  job_level?: string;
  status?: PositionStatus;
}

export interface PositionCreatePayload {
  code: string;
  name: string;
  org_id?: string;
  job_level?: string;
  headcount?: number;
  status?: PositionStatus;
}

export interface PositionUpdatePayload {
  code?: string;
  name?: string;
  org_id?: string;
  job_level?: string;
  headcount?: number;
  status?: PositionStatus;
}
