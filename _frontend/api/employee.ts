/**
 * 员工域 api（admin 层 /hr/admin/v1：花名册/建档编辑/统计/导入/账号/扩展属性/异动）
 */

import { get, post, put, del } from "@/framework/api/client";

import type { ApiResponse } from "@/framework/api/types";

import type {
  AccountOpenResult,
  AttributeValueItem,
  ChangeCreatePayload,
  ChangeRecord,
  Employee,
  EmployeeCreatePayload,
  EmployeeDetail,
  EmployeeImportResult,
  EmployeeImportRowPayload,
  EmployeeQuery,
  EmployeeStats,
  EmployeeUpdatePayload,
  SensitiveView,
} from "@/hr/types/employee";

/** 员工分页列表（已离职默认不展示，需显式按状态筛选） */
export function listEmployees(query: EmployeeQuery): Promise<ApiResponse<Employee[]>> {
  return get<ApiResponse<Employee[]>>("/hr/admin/v1/employees", { params: query });
}

/** 员工统计卡（在编/试用/本月新入职/离职率；org_id 联动） */
export function getEmployeeStats(orgId?: string): Promise<ApiResponse<EmployeeStats>> {
  return get<ApiResponse<EmployeeStats>>("/hr/admin/v1/employees/stats", {
    params: orgId ? { org_id: orgId } : undefined,
  });
}

/** 员工详情（敏感字段掩码） */
export function getEmployeeDetail(employeeId: string): Promise<ApiResponse<EmployeeDetail>> {
  return get<ApiResponse<EmployeeDetail>>(`/hr/admin/v1/employees/${employeeId}`);
}

/** 敏感字段明文（hr:employee:sensitive；明文查看由后端写审计） */
export function getSensitiveView(employeeId: string): Promise<ApiResponse<SensitiveView>> {
  return get<ApiResponse<SensitiveView>>(`/hr/admin/v1/employees/${employeeId}/sensitive`);
}

/** 入职建档（自动生成工号 + 写 hire 异动流水） */
export function createEmployee(payload: EmployeeCreatePayload): Promise<ApiResponse<Employee>> {
  return post<ApiResponse<Employee>>("/hr/admin/v1/employees", payload);
}

/** 员工编辑（敏感字段提交掩码/空表示保留原值） */
export function updateEmployee(
  employeeId: string,
  payload: EmployeeUpdatePayload,
): Promise<ApiResponse<Employee>> {
  return put<ApiResponse<Employee>>(`/hr/admin/v1/employees/${employeeId}`, payload);
}

/** 删除员工（仅离职员可删） */
export function deleteEmployee(employeeId: string): Promise<ApiResponse<null>> {
  return del<ApiResponse<null>>(`/hr/admin/v1/employees/${employeeId}`);
}

/** 批量导入（dryRun 预检不落库） */
export function importEmployees(payload: {
  dry_run: boolean;
  rows: EmployeeImportRowPayload[];
}): Promise<ApiResponse<EmployeeImportResult>> {
  return post<ApiResponse<EmployeeImportResult>>("/hr/admin/v1/employees/import", payload);
}

/** 开通系统账号（inner 调 iam 建用户回填 user_id；初始密码一次性回显） */
export function openAccount(employeeId: string): Promise<ApiResponse<AccountOpenResult>> {
  return post<ApiResponse<AccountOpenResult>>(`/hr/admin/v1/employees/${employeeId}/open-account`);
}

/** 员工扩展属性（定义 + 值合并结构） */
export function getEmployeeAttributes(
  employeeId: string,
): Promise<ApiResponse<AttributeValueItem[]>> {
  return get<ApiResponse<AttributeValueItem[]>>(`/hr/admin/v1/employees/${employeeId}/attributes`);
}

/** 保存员工扩展属性值（values 以 definition_id 为键；按定义校验后 upsert） */
export function saveEmployeeAttributes(
  employeeId: string,
  values: Record<string, unknown>,
): Promise<ApiResponse<{ written: number }>> {
  return put<ApiResponse<{ written: number }>>(
    `/hr/admin/v1/employees/${employeeId}/attributes`,
    { values },
  );
}

/** 员工异动历史（成长记录时间线数据源，倒序由前端处理） */
export function listEmployeeChanges(
  employeeId: string,
  query: { page?: number; page_size?: number } = {},
): Promise<ApiResponse<ChangeRecord[]>> {
  return get<ApiResponse<ChangeRecord[]>>(`/hr/admin/v1/employees/${employeeId}/changes`, {
    params: query,
  });
}

/** 发起异动（转正/调岗/调薪/离职） */
export function createChange(payload: ChangeCreatePayload): Promise<ApiResponse<ChangeRecord>> {
  return post<ApiResponse<ChangeRecord>>("/hr/admin/v1/employee-changes", payload);
}
