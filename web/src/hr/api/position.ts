/**
 * 岗位域 api（admin 层 /hr/admin/v1：岗位 CRUD + 在岗人数实时统计）
 */

import { get, post, put, del } from "@/framework/api/client";

import type { ApiResponse } from "@/framework/api/types";

import type {
  Position,
  PositionCreatePayload,
  PositionQuery,
  PositionUpdatePayload,
} from "@/hr/types/position";

/** 岗位分页列表（在岗人数实时统计） */
export function listPositions(query: PositionQuery): Promise<ApiResponse<Position[]>> {
  return get<ApiResponse<Position[]>>("/hr/admin/v1/positions", { params: query });
}

/** 岗位详情（含在岗人数） */
export function getPosition(positionId: string): Promise<ApiResponse<Position>> {
  return get<ApiResponse<Position>>(`/hr/admin/v1/positions/${positionId}`);
}

/** 创建岗位（编码租户内唯一，冲突返回 409） */
export function createPosition(payload: PositionCreatePayload): Promise<ApiResponse<Position>> {
  return post<ApiResponse<Position>>("/hr/admin/v1/positions", payload);
}

/** 更新岗位（停用后不可被员工建档与招聘需求选中） */
export function updatePosition(
  positionId: string,
  payload: PositionUpdatePayload,
): Promise<ApiResponse<Position>> {
  return put<ApiResponse<Position>>(`/hr/admin/v1/positions/${positionId}`, payload);
}

/** 删除岗位（在岗员工 > 0 不可删除，仅可停用） */
export function deletePosition(positionId: string): Promise<ApiResponse<null>> {
  return del<ApiResponse<null>>(`/hr/admin/v1/positions/${positionId}`);
}
