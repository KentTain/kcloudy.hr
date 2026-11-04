/**
 * 异动域 api（admin 层 /hr/admin/v1：跨员工流水检索；单员工历史与发起在 employee.ts）
 */

import { get, post } from "@/framework/api/client";

import type { ApiResponse } from "@/framework/api/types";

import type { ChangeQuery, ChangeRecord } from "@/hr/types/employee";

/** 跨员工异动流水分页（类型/时间段/组织筛选；组织按快照 after_data.org_id） */
export function listChangeRecords(query: ChangeQuery): Promise<ApiResponse<ChangeRecord[]>> {
  return get<ApiResponse<ChangeRecord[]>>("/hr/admin/v1/employee-changes", { params: query });
}

/** 异动流水详情（前后快照） */
export function getChangeRecord(changeId: string): Promise<ApiResponse<ChangeRecord>> {
  return get<ApiResponse<ChangeRecord>>(`/hr/admin/v1/employee-changes/${changeId}`);
}

/** 移交异动记录业务归属人（owner_id 可变归属；目标须同租户在册） */
export function transferChangeRecord(
  changeId: string,
  ownerId: string
): Promise<ApiResponse<ChangeRecord>> {
  return post<ApiResponse<ChangeRecord>>(`/hr/admin/v1/employee-changes/${changeId}/transfer`, {
    owner_id: ownerId,
  });
}
