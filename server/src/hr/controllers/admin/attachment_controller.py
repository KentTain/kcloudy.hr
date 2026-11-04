"""材料附件控制器 - 管理端

MinIO 私有桶上传 / 列表（证件类受 sensitive 权限裁剪）/ 受控下载（写审计）/ 删除。
权限码 hr:attachment:read/write/delete + hr:employee:sensitive。
"""

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from framework.clients.iam_client import get_iam_client
from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import (
    get_current_user_id,
    optional_permission,
    require_permission,
)

from hr.services.attachment_service import attachment_service

router = APIRouter()


@router.post("/employees/{employee_id}/attachments")
async def upload_attachment(
    employee_id: str,
    doc_type: str,
    file: UploadFile,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:attachment:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """上传材料附件（MinIO 私有桶，落引用行）"""
    data = await file.read()
    result = await attachment_service.upload(
        session,
        employee_id=employee_id,
        doc_type=doc_type,
        file_name=file.filename or "unnamed",
        data=data,
        content_type=file.content_type,
    )
    return ApiResponse.success(data=result)


@router.get("/employees/{employee_id}/attachments")
async def list_attachments(
    employee_id: str,
    can_sensitive: bool = Depends(optional_permission("hr:employee:sensitive")),
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:attachment:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """附件列表（证件类档案仅 hr:employee:sensitive 可见）"""
    items = await attachment_service.list_attachments(
        session, employee_id, include_sensitive=can_sensitive
    )
    return ApiResponse.success(data=items)


@router.get("/attachments/{attachment_id}/download-url")
async def get_attachment_download_url(
    attachment_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:attachment:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """受控下载：签发短期预签名 URL（调用即写审计日志）"""
    result = await attachment_service.get_download_url(session, attachment_id)
    await get_iam_client().create_audit_log(
        session,
        business_domain="hr",
        operation_type="download",
        resource_type="employee_attachment",
        resource_name=result["file_name"],
        resource_id=attachment_id,
        detail={"operator_id": user_id},
    )
    return ApiResponse.success(data=result)


@router.delete("/attachments/{attachment_id}")
async def delete_attachment(
    attachment_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:attachment:delete")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """删除附件（引用行 + MinIO 对象）"""
    await attachment_service.delete_attachment(session, attachment_id)
    return ApiResponse.success(data={"deleted": attachment_id})
