/**
 * 页面支撑数据 api（iam 组织树 / hr 岗位选项 / 员工薪酬信息——跨域只读消费）
 */

import { get } from "@/framework/api/client";

import type { ApiResponse } from "@/framework/api/types";

import type {
  BandComparison,
  OrgTreeNode,
  PositionOption,
  SalaryItemOption,
  SalaryPackageRecord,
} from "@/hr/types/employee";

/** iam 组织树（与 iam 组织管理页同源；hr 侧不做组织维护） */
export function getOrgTree(): Promise<ApiResponse<OrgTreeNode[]>> {
  return get<ApiResponse<OrgTreeNode[]>>("/iam/admin/v1/organizations/tree");
}

/** 生效岗位下拉选项（建档/异动弹窗选用；需 hr:position:read，无权限时调用方降级空选项） */
export function getPositionOptions(orgId?: string): Promise<ApiResponse<PositionOption[]>> {
  return get<ApiResponse<PositionOption[]>>("/hr/admin/v1/positions/options", {
    params: orgId ? { org_id: orgId } : undefined,
  });
}

/** 员工定薪历史（区间行，item 级） */
export function listEmployeeSalaryPackages(
  employeeId: string,
): Promise<ApiResponse<SalaryPackageRecord[]>> {
  return get<ApiResponse<SalaryPackageRecord[]>>(
    `/hr/admin/v1/employees/${employeeId}/salary-packages`,
  );
}

/** 薪带对标（方案总额相对职级带宽位置） */
export function getBandComparison(employeeId: string): Promise<ApiResponse<BandComparison>> {
  return get<ApiResponse<BandComparison>>(`/hr/admin/v1/employees/${employeeId}/salary-comparison`);
}

/** 薪酬项选项（调薪弹窗选用；需 hr:salary_item:read，无权限时调用方降级空选项） */
export function listSalaryItemOptions(): Promise<ApiResponse<SalaryItemOption[]>> {
  return get<ApiResponse<SalaryItemOption[]>>("/hr/admin/v1/salary-items", {
    params: { page: 1, page_size: 100 },
  });
}
