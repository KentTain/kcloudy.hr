/**
 * 薪酬域 api（admin 层 /hr/admin/v1：薪酬项字典 CRUD + 类别字典读写 + 职级薪带版本管理）
 */

import { get, post, put, del } from "@/framework/api/client";

import type { ApiResponse } from "@/framework/api/types";

import type {
  PayrollEntry,
  PayrollEntryUpdatePayload,
  PayrollRun,
  PayrollRunQuery,
  SalaryBand,
  SalaryBandCreatePayload,
  SalaryBandQuery,
  SalaryBandUpdatePayload,
  SalaryItem,
  SalaryItemCreatePayload,
  SalaryItemQuery,
  SalaryItemUpdatePayload,
  SalaryPackageAdjustPayload,
} from "@/hr/types/salary";

/* ── 薪酬项 ── */

/** 薪酬项分页列表（类别筛选 + 编码/名称关键词） */
export function listSalaryItems(query: SalaryItemQuery): Promise<ApiResponse<SalaryItem[]>> {
  return get<ApiResponse<SalaryItem[]>>("/hr/admin/v1/salary-items", { params: query });
}

/** 创建薪酬项（编码租户唯一，创建后不可修改） */
export function createSalaryItem(
  payload: SalaryItemCreatePayload,
): Promise<ApiResponse<SalaryItem>> {
  return post<ApiResponse<SalaryItem>>("/hr/admin/v1/salary-items", payload);
}

/** 更新薪酬项（编码不可修改；停用经 can_edit=false） */
export function updateSalaryItem(
  itemId: string,
  payload: SalaryItemUpdatePayload,
): Promise<ApiResponse<SalaryItem>> {
  return put<ApiResponse<SalaryItem>>(`/hr/admin/v1/salary-items/${itemId}`, payload);
}

/** 删除薪酬项（被定薪方案或发薪明细引用时拒绝：只可停用） */
export function deleteSalaryItem(itemId: string): Promise<ApiResponse<null>> {
  return del<ApiResponse<null>>(`/hr/admin/v1/salary-items/${itemId}`);
}

/* ── 类别字典（hr_salary_setting.categories 租户配置） ── */

/** 薪酬类别字典（转发租户配置） */
export function getSalaryCategories(): Promise<ApiResponse<{ categories: string[] }>> {
  return get<ApiResponse<{ categories: string[] }>>("/hr/admin/v1/salary-setting");
}

/** 类别字典维护（已绑定薪酬项的类别后端拒绝删除） */
export function updateSalaryCategories(categories: string[]): Promise<ApiResponse<{ categories: string[] }>> {
  return put<ApiResponse<{ categories: string[] }>>("/hr/admin/v1/salary-setting", { categories });
}

/* ── 职级薪带 ── */

/** 薪带对照表（职级/生效状态筛选：active=当前生效 / history=历史版本 / upcoming=未生效） */
export function listSalaryBands(query: SalaryBandQuery): Promise<ApiResponse<SalaryBand[]>> {
  return get<ApiResponse<SalaryBand[]>>("/hr/admin/v1/salary-bands", { params: query });
}

/** 新建薪带版本（min ≤ mid ≤ max；当前版本自动闭合；重叠区间拒绝） */
export function createSalaryBand(
  payload: SalaryBandCreatePayload,
): Promise<ApiResponse<SalaryBand>> {
  return post<ApiResponse<SalaryBand>>("/hr/admin/v1/salary-bands", payload);
}

/** 更新薪带（仅未生效版本可编辑） */
export function updateSalaryBand(
  bandId: string,
  payload: SalaryBandUpdatePayload,
): Promise<ApiResponse<SalaryBand>> {
  return put<ApiResponse<SalaryBand>>(`/hr/admin/v1/salary-bands/${bandId}`, payload);
}

/** 删除薪带（仅未生效版本可删除） */
export function deleteSalaryBand(bandId: string): Promise<ApiResponse<null>> {
  return del<ApiResponse<null>>(`/hr/admin/v1/salary-bands/${bandId}`);
}

/* ── 定薪调薪（员工区间版本化；对标只读走 @/hr/api/reference） ── */

/** 调薪（一事一流水：按项逐行闭合旧区间 + 生成新区间，返回新区间行） */
export function adjustSalaryPackage(
  employeeId: string,
  payload: SalaryPackageAdjustPayload,
): Promise<ApiResponse<unknown[]>> {
  return post<ApiResponse<unknown[]>>(`/hr/admin/v1/employees/${employeeId}/salary-packages`, payload);
}

/* ── 发薪批次 ── */

/** 发薪批次列表（期间倒序） */
export function listPayrollRuns(query: PayrollRunQuery): Promise<ApiResponse<PayrollRun[]>> {
  return get<ApiResponse<PayrollRun[]>>("/hr/admin/v1/payroll-runs", { params: query });
}

/** 创建批次（期间租户唯一）并异步试算（返回 task_id） */
export function createPayrollRun(period: string): Promise<ApiResponse<{ run: PayrollRun; task_id: string }>> {
  return post<ApiResponse<{ run: PayrollRun; task_id: string }>>("/hr/admin/v1/payroll-runs", { period });
}

/** 批次详情 */
export function getPayrollRun(runId: string): Promise<ApiResponse<PayrollRun>> {
  return get<ApiResponse<PayrollRun>>(`/hr/admin/v1/payroll-runs/${runId}`);
}

/** 批次明细（员工 × 薪酬项行；矩阵列由薪酬项字典动态生成） */
export function listPayrollEntries(runId: string, pageSize = 200): Promise<ApiResponse<PayrollEntry[]>> {
  return get<ApiResponse<PayrollEntry[]>>(`/hr/admin/v1/payroll-runs/${runId}/entries`, {
    params: { page: 1, page_size: pageSize },
  });
}

/** 明细人工修正（仅 draft 态；金额修改须填备注留痕） */
export function updatePayrollEntry(
  runId: string,
  entryId: string,
  payload: PayrollEntryUpdatePayload,
): Promise<ApiResponse<PayrollEntry>> {
  return put<ApiResponse<PayrollEntry>>(`/hr/admin/v1/payroll-runs/${runId}/entries/${entryId}`, payload);
}

/** 确认批次（明细锁死；写审计） */
export function confirmPayrollRun(runId: string): Promise<ApiResponse<PayrollRun>> {
  return post<ApiResponse<PayrollRun>>(`/hr/admin/v1/payroll-runs/${runId}/confirm`);
}

/** 标记发放（生成个人薪酬单，员工自助可查；写审计） */
export function payPayrollRun(runId: string): Promise<ApiResponse<PayrollRun>> {
  return post<ApiResponse<PayrollRun>>(`/hr/admin/v1/payroll-runs/${runId}/pay`);
}

/** 取消批次（已发放不可取消；写审计） */
export function cancelPayrollRun(runId: string): Promise<ApiResponse<PayrollRun>> {
  return post<ApiResponse<PayrollRun>>(`/hr/admin/v1/payroll-runs/${runId}/cancel`);
}

/** 导出薪酬明细（写审计：操作人/期间/行数；返回 JSON 行集） */
/** 标准代发文件导出（xlsx；confirmed/paid 态；写敏感审计） */
export function exportPayrollRun(runId: string): Promise<ApiResponse<{ filename: string; content_base64: string }>> {
  return get<ApiResponse<{ filename: string; content_base64: string }>>(`/hr/admin/v1/payroll-runs/${runId}/export`);
}
