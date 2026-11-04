/**
 * 员工域类型（对齐 server/python/src/hr/schemas/employee.py、attribute.py、
 * contract.py、change.py；薪酬域对齐 salary.py 定薪区间与薪带对标）
 */

import type { BadgeVariants } from "@/components/ui/badge";

/** ── 枚举与文案 ── */

export type EmployeeStatus = "pending" | "probation" | "regular" | "intern" | "offboarded";

export const EMPLOYEE_STATUS_LABELS: Record<EmployeeStatus, string> = {
  pending: "待入职",
  probation: "试用期",
  regular: "正式",
  intern: "实习",
  offboarded: "已离职",
};

/** 状态徽标配色：在职正向、待入职中性、离职危险 */
export const EMPLOYEE_STATUS_VARIANTS: Record<EmployeeStatus, BadgeVariants> = {
  pending: "secondary",
  probation: "default",
  regular: "default",
  intern: "outline",
  offboarded: "destructive",
};

/** 在职 = 非已离职（账号开通/异动/合同等入口的状态门槛） */
export function isActiveEmployee(status: string): boolean {
  return status !== "offboarded";
}

export type ChangeType =
  | "hire"
  | "probate"
  | "transfer"
  | "level_change"
  | "salary_change"
  | "offboard";

export const CHANGE_TYPE_LABELS: Record<ChangeType, string> = {
  hire: "入职",
  probate: "转正",
  transfer: "调岗",
  level_change: "职级变更",
  salary_change: "调薪",
  offboard: "离职",
};

/** 员工详情抽屉「人事异动」可发起的类型（hire 由建档/导入自动写入） */
export const MANUAL_CHANGE_TYPES: ChangeType[] = [
  "probate",
  "transfer",
  "level_change",
  "salary_change",
  "offboard",
];

export type ContractStatus = "active" | "expired" | "terminated";

export const CONTRACT_STATUS_LABELS: Record<ContractStatus, string> = {
  active: "生效中",
  expired: "已到期",
  terminated: "已终止",
};

/** 合同类型（后端自由字符串，前端约定常用取值） */
export const CONTRACT_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "fixed", label: "固定期限" },
  { value: "open", label: "无固定期限" },
  { value: "intern", label: "实习协议" },
  { value: "labor", label: "劳务合同" },
];

export function contractTypeLabel(value: string | null): string {
  return CONTRACT_TYPE_OPTIONS.find((option) => option.value === value)?.label ?? value ?? "--";
}

export type AttachmentDocType = "id_card" | "education" | "labor_contract" | "onboard" | "other";

export const ATTACHMENT_DOC_TYPES: { value: AttachmentDocType; label: string }[] = [
  { value: "id_card", label: "身份证件" },
  { value: "education", label: "学历证明" },
  { value: "labor_contract", label: "劳动合同" },
  { value: "onboard", label: "入职材料" },
  { value: "other", label: "其他" },
];

export const ATTRIBUTE_DATA_TYPE_LABELS: Record<string, string> = {
  string: "文本",
  integer: "整数",
  decimal: "小数",
  date_time: "日期",
  boolean: "布尔",
  json: "JSON",
};

/** 定薪/调薪原因（对齐 SalaryChangeReason） */
export const SALARY_REASON_LABELS: Record<string, string> = {
  hire: "入职定薪",
  adjust: "调薪",
  promotion: "晋升调薪",
  perf: "绩效联动",
};

/** ── 员工主档 ── */

export interface Employee {
  id: string;
  employee_no: string;
  name: string;
  gender: string | null;
  phone: string | null;
  work_email: string | null;
  org_id: string | null;
  position_id: string | null;
  job_level: string | null;
  status: EmployeeStatus;
  hire_date: string;
  regular_date: string | null;
  offboard_date: string | null;
  user_id: string | null;
  has_account: boolean;
}

export interface EmployeeDetail extends Employee {
  birth_date: string | null;
  id_card_masked: string | null;
  bank_card_masked: string | null;
  bank_name: string | null;
}

/** 敏感字段明文视图（hr:employee:sensitive；明文查看由后端写审计） */
export interface SensitiveView {
  id_card: string | null;
  bank_card: string | null;
}

export interface EmployeeQuery {
  page: number;
  page_size: number;
  keyword?: string;
  org_id?: string;
  status?: EmployeeStatus;
  position_id?: string;
  job_level?: string;
}

export interface EmployeeStats {
  active_count: number;
  probation_count: number;
  month_hired_count: number;
  turnover_rate: number;
}

export interface EmployeeCreatePayload {
  name: string;
  gender?: string;
  birth_date?: string;
  id_card?: string;
  bank_card?: string;
  bank_name?: string;
  phone?: string;
  work_email?: string;
  org_id?: string;
  position_id?: string;
  job_level?: string;
  hire_date: string;
  attribute_values?: Record<string, unknown>;
}

export interface EmployeeUpdatePayload {
  name?: string;
  gender?: string;
  birth_date?: string;
  id_card?: string;
  bank_card?: string;
  bank_name?: string;
  phone?: string;
  work_email?: string;
  org_id?: string;
  position_id?: string;
  job_level?: string;
}

export interface AccountOpenResult {
  employee_id: string;
  user_id: string;
  username: string;
  initial_password: string;
}

/** ── 批量导入 ── */

export interface EmployeeImportRowPayload {
  name: string;
  gender?: string;
  birth_date?: string;
  id_card?: string;
  phone?: string;
  work_email?: string;
  org_id?: string;
  position_id?: string;
  job_level?: string;
  hire_date: string;
  status?: EmployeeStatus;
}

export interface EmployeeImportResult {
  dry_run: boolean;
  total: number;
  success_count: number;
  failure_count: number;
  rows: { row_index: number; success: boolean; employee_no: string | null; error: string | null }[];
}

/** ── 扩展属性（EAV）── */

export interface FieldGroup {
  id: string;
  code: string;
  name: string;
  sort: number;
}

export interface FieldDefinition {
  id: string;
  group_id: string;
  name: string;
  data_type: string;
  ext_data: Record<string, unknown> | null;
  is_require: boolean;
  can_edit: boolean;
  sort: number;
}

/** 定义 + 员工值合并结构（未配置值回 null；敏感值无权限时回掩码串） */
export interface AttributeValueItem {
  definition_id: string;
  group_id: string;
  name: string;
  data_type: string;
  ext_data: Record<string, unknown> | null;
  is_require: boolean;
  can_edit: boolean;
  sort: number;
  value: unknown;
  raw_value: string | null;
}

/** ── 合同与材料附件 ── */

export interface Contract {
  id: string;
  employee_id: string;
  contract_no: string;
  contract_type: string;
  start_date: string;
  end_date: string | null;
  company: string | null;
  signed_date: string | null;
  status: ContractStatus;
  expiry_remind: boolean;
  attachment: string | null;
  remark: string | null;
}

export interface ContractCreatePayload {
  employee_id: string;
  contract_no: string;
  contract_type: string;
  start_date: string;
  end_date?: string;
  company?: string;
  signed_date?: string;
  expiry_remind?: boolean;
  attachment?: string;
  remark?: string;
}

export interface Attachment {
  id: string;
  employee_id: string;
  doc_type: string;
  file_id: string;
  file_name: string;
  file_url: string | null;
}

/** ── 异动流水 ── */

export interface ChangeRecord {
  id: string;
  employee_id: string;
  change_type: ChangeType;
  before_data: Record<string, unknown> | null;
  after_data: Record<string, unknown> | null;
  effective_date: string;
  operator_id: string | null;
}

/** 跨员工异动流水分页查询（GET /employee-changes；组织按快照 after_data.org_id 过滤） */
export interface ChangeQuery {
  page: number;
  page_size: number;
  employee_id?: string;
  change_type?: ChangeType;
  org_id?: string;
  keyword?: string;
  start_date?: string;
  end_date?: string;
}

export interface ChangeCreatePayload {
  employee_id: string;
  change_type: ChangeType;
  effective_date: string;
  org_id?: string;
  position_id?: string;
  job_level?: string;
  salary_items?: { item_id: string; amount: number }[];
  reason?: string;
  remark?: string;
}

/** ── 薪酬信息（详情抽屉只读消费）── */

export interface SalaryPackageRecord {
  id: string;
  employee_id: string;
  item_id: string;
  item_code: string | null;
  item_name: string | null;
  category: string | null;
  amount: number;
  reason: string;
  effective_from: string;
  effective_to: string | null;
}

/** 薪带对标（方案总额相对职级带宽位置；position=below/within/above/none） */
export interface BandComparison {
  job_level: string;
  total: number;
  band_min: number | null;
  band_max: number | null;
  position: string;
}

/** ── 页面支撑数据 ── */

/** iam 组织树节点（hr 侧最小集；树维护在 iam 组织管理） */
export interface OrgTreeNode {
  id: string;
  name: string;
  parent_id?: string | null;
  status?: string;
  total_member_count?: number;
  children?: OrgTreeNode[];
}

export interface PositionOption {
  id: string;
  name: string;
  code: string;
  job_level: string | null;
  status: string;
}

/** 薪酬项下拉选项（调薪弹窗） */
export interface SalaryItemOption {
  id: string;
  name: string;
  code: string;
  category: string | null;
}
