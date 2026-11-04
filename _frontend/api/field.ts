/**
 * 员工扩展属性定义 api（属性组 / 定义管理，admin 层 /hr/admin/v1）
 */

import { get, post, put, del } from "@/framework/api/client";

import type { ApiResponse } from "@/framework/api/types";

import type { FieldDefinition, FieldGroup } from "@/hr/types/employee";

/** 属性组列表 */
export function listFieldGroups(): Promise<ApiResponse<FieldGroup[]>> {
  return get<ApiResponse<FieldGroup[]>>("/hr/admin/v1/field-groups");
}

/** 新增属性组 */
export function createFieldGroup(payload: {
  code: string;
  name: string;
  sort?: number;
}): Promise<ApiResponse<FieldGroup>> {
  return post<ApiResponse<FieldGroup>>("/hr/admin/v1/field-groups", payload);
}

/** 更新属性组 */
export function updateFieldGroup(
  groupId: string,
  payload: { name?: string; sort?: number },
): Promise<ApiResponse<FieldGroup>> {
  return put<ApiResponse<FieldGroup>>(`/hr/admin/v1/field-groups/${groupId}`, payload);
}

/** 删除属性组 */
export function deleteFieldGroup(groupId: string): Promise<ApiResponse<null>> {
  return del<ApiResponse<null>>(`/hr/admin/v1/field-groups/${groupId}`);
}

/** 属性定义列表（group_id 筛选） */
export function listFieldDefinitions(groupId?: string): Promise<ApiResponse<FieldDefinition[]>> {
  return get<ApiResponse<FieldDefinition[]>>("/hr/admin/v1/field-definitions", {
    params: groupId ? { group_id: groupId } : undefined,
  });
}

/** 新增属性定义 */
export function createFieldDefinition(payload: {
  group_id: string;
  name: string;
  data_type: string;
  ext_data?: Record<string, unknown>;
  is_require?: boolean;
  can_edit?: boolean;
  sort?: number;
}): Promise<ApiResponse<FieldDefinition>> {
  return post<ApiResponse<FieldDefinition>>("/hr/admin/v1/field-definitions", payload);
}

/** 更新属性定义（data_type 变更由后端校验存量值可解析） */
export function updateFieldDefinition(
  definitionId: string,
  payload: {
    name?: string;
    data_type?: string;
    ext_data?: Record<string, unknown>;
    is_require?: boolean;
    can_edit?: boolean;
    sort?: number;
  },
): Promise<ApiResponse<FieldDefinition>> {
  return put<ApiResponse<FieldDefinition>>(
    `/hr/admin/v1/field-definitions/${definitionId}`,
    payload,
  );
}

/** 删除属性定义（须先清理存量值） */
export function deleteFieldDefinition(definitionId: string): Promise<ApiResponse<null>> {
  return del<ApiResponse<null>>(`/hr/admin/v1/field-definitions/${definitionId}`);
}
