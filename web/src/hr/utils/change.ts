/**
 * 异动流水前后对比派生：变更字段逐项「字段：前 → 后」
 */
import { EMPLOYEE_STATUS_LABELS, type ChangeRecord } from "@/hr/types/employee";

/** 展示值格式化：状态走文案、组织/岗位 ID 经解析为名称、其余原样（null → "--"） */
function displayValue(
  key: string,
  value: unknown,
  resolveName: (key: string, value: unknown) => string,
): string {
  if (value === null || value === undefined || value === "") return "--";
  if (key === "status") return EMPLOYEE_STATUS_LABELS[value as keyof typeof EMPLOYEE_STATUS_LABELS] ?? String(value);
  if (key === "org_id" || key === "position_id") return resolveName(key, value);
  return String(value);
}

export const CHANGE_FIELD_LABELS: Record<string, string> = {
  name: "姓名",
  org_id: "组织",
  position_id: "岗位",
  job_level: "职级",
  status: "状态",
  offboard_reason: "离职原因",
  remark: "备注",
  salary_items: "薪酬方案",
};

/** 变更摘要行（如「组织：研发部 → 交付部」）；调薪行特殊展开薪酬项计数 */
export function changeDiffLines(
  record: ChangeRecord,
  resolveName: (key: string, value: unknown) => string = (_key, value) => String(value ?? "--"),
): string[] {
  const before = record.before_data ?? {};
  const after = record.after_data ?? {};
  const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
  const lines: string[] = [];
  for (const key of keys) {
    if (key === "salary_items") {
      const items = after.salary_items as { item_id: string; amount: number }[] | undefined;
      lines.push(`薪酬方案：调整 ${Array.isArray(items) ? items.length : 0} 项`);
      continue;
    }
    const beforeValue = before[key];
    const afterValue = after[key];
    if (JSON.stringify(beforeValue) === JSON.stringify(afterValue)) continue;
    const label = CHANGE_FIELD_LABELS[key] ?? key;
    lines.push(
      `${label}：${displayValue(key, beforeValue, resolveName)} → ${displayValue(key, afterValue, resolveName)}`,
    );
  }
  if (record.change_type === "hire" && !lines.length) {
    lines.push("入职建档");
  }
  return lines;
}
