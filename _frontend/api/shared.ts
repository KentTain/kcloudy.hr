/**
 * hr 模块 api 封装约定
 *
 * - 请求工具统一用 `apiClient`（@/framework/api/client）的 get/post/put/del，
 *   baseURL 前缀 `/hr/admin/v1`（admin 层）或 `/hr/console/v1`（console 自助层）；
 * - 响应信封为 ApiResponse（code/msg/data/total/page/page_size），拦截器已解包
 *   axios 层，拿到的是 HTTP body 本体；
 * - api 文件按子域组织（employee.ts / recruiting.ts / salary.ts ...），
 *   函数命名 listX/getX/createX/updateX/deleteX；
 * - 权限码不出现在 api 层（路由 meta.permissions + 页面 v-permission 控制）。
 */

import type { ApiResponse } from "@/framework/api/types";

/** 列表信封（data 裸数组 + 顶层 total）→ DataTable remoteFetchFn 适配形态 */
export function toPage<T>(res: ApiResponse<T[]>): { data: T[]; total: number } {
  return { data: res.data ?? [], total: res.total ?? 0 };
}
