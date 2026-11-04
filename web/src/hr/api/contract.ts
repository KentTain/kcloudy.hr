/**
 * 合同与材料附件 api（admin 层 /hr/admin/v1）
 */

import { get, post, put, del } from "@/framework/api/client";

import type { ApiResponse } from "@/framework/api/types";

import type { Attachment, Contract, ContractCreatePayload } from "@/hr/types/employee";

/** 员工合同列表 */
export function listEmployeeContracts(employeeId: string): Promise<ApiResponse<Contract[]>> {
  return get<ApiResponse<Contract[]>>(`/hr/admin/v1/employees/${employeeId}/contracts`);
}

/** 新签合同 */
export function createContract(payload: ContractCreatePayload): Promise<ApiResponse<Contract>> {
  return post<ApiResponse<Contract>>("/hr/admin/v1/contracts", payload);
}

/** 续签（旧合同区间闭合 + 新合同生效） */
export function renewContract(
  contractId: string,
  payload: Omit<ContractCreatePayload, "employee_id">,
): Promise<ApiResponse<Contract>> {
  return post<ApiResponse<Contract>>(`/hr/admin/v1/contracts/${contractId}/renew`, payload);
}

/** 终止合同 */
export function terminateContract(contractId: string): Promise<ApiResponse<Contract>> {
  return post<ApiResponse<Contract>>(`/hr/admin/v1/contracts/${contractId}/terminate`);
}

/** 删除合同 */
export function deleteContract(contractId: string): Promise<ApiResponse<null>> {
  return del<ApiResponse<null>>(`/hr/admin/v1/contracts/${contractId}`);
}

/** 员工材料附件列表（证件类档案仅 hr:employee:sensitive 可见） */
export function listEmployeeAttachments(employeeId: string): Promise<ApiResponse<Attachment[]>> {
  return get<ApiResponse<Attachment[]>>(`/hr/admin/v1/employees/${employeeId}/attachments`);
}

/** 上传材料附件（multipart；MinIO 私有桶） */
export function uploadEmployeeAttachment(
  employeeId: string,
  docType: string,
  file: File,
): Promise<ApiResponse<Attachment>> {
  const form = new FormData();
  form.append("file", file);
  return post<ApiResponse<Attachment>>(
    `/hr/admin/v1/employees/${employeeId}/attachments`,
    form,
    { params: { doc_type: docType } },
  );
}

/** 受控下载链接（调用即写审计） */
export function getAttachmentDownloadUrl(
  attachmentId: string,
): Promise<ApiResponse<{ file_name: string; url: string }>> {
  return get<ApiResponse<{ file_name: string; url: string }>>(
    `/hr/admin/v1/attachments/${attachmentId}/download-url`,
  );
}

/** 删除附件（写审计） */
export function deleteAttachment(attachmentId: string): Promise<ApiResponse<null>> {
  return del<ApiResponse<null>>(`/hr/admin/v1/attachments/${attachmentId}`);
}
