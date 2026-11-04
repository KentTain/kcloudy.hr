"""材料附件服务：MinIO 私有桶上传 / 受控下载（写审计）/ 删除"""

import uuid

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, NotFoundError
from framework.storage.tenant_storage import TenantMinioStorage

from hr.models import Employee, EmployeeAttachment
from hr.schemas.contract import (
    AttachmentResponse,
    AttachmentUploadResponse,
)

_logger = logger.bind(name=__name__)

# 档案类型（模型注释同源）
DOC_TYPES = {"id_card", "education", "labor_contract", "onboard", "other"}
# 证件类档案：受 hr:employee:sensitive 权限裁剪
SENSITIVE_DOC_TYPES = {"id_card"}

HR_BUCKET = "hr"


class AttachmentService:
    """员工材料附件业务"""

    async def upload(
        self,
        session: AsyncSession,
        *,
        employee_id: str,
        doc_type: str,
        file_name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> AttachmentUploadResponse:
        """上传附件到 MinIO 私有桶并落引用行"""
        if doc_type not in DOC_TYPES:
            raise BadRequestError(
                f"不支持的档案类型: {doc_type}（可选 {sorted(DOC_TYPES)}）"
            )
        employee = await session.get(Employee, employee_id)
        if not employee:
            raise NotFoundError(f"员工 {employee_id} 不存在")

        file_id = uuid.uuid4().hex
        object_name = f"employees/{employee_id}/{file_id}/{file_name}"
        await TenantMinioStorage.upload(HR_BUCKET, object_name, data, content_type)

        row = EmployeeAttachment(
            employee_id=employee_id,
            doc_type=doc_type,
            file_id=file_id,
            file_url=object_name,
            file_name=file_name,
        )
        session.add(row)
        await session.flush()
        _logger.info(f"附件上传: employee={employee_id} doc_type={doc_type} file={file_name}")
        return AttachmentUploadResponse(
            id=row.id,
            employee_id=employee_id,
            doc_type=doc_type,
            file_name=file_name,
        )

    async def list_attachments(
        self, session: AsyncSession, employee_id: str, *, include_sensitive: bool
    ) -> list[AttachmentResponse]:
        """附件列表（证件类受 sensitive 权限裁剪）"""
        result = await session.execute(
            select(EmployeeAttachment)
            .where(EmployeeAttachment.employee_id == employee_id)
            .order_by(EmployeeAttachment.created_at.desc())
        )
        return [
            AttachmentResponse.model_validate(row)
            for row in result.scalars().all()
            if include_sensitive or row.doc_type not in SENSITIVE_DOC_TYPES
        ]

    async def get_download_url(
        self, session: AsyncSession, attachment_id: str
    ) -> dict:
        """受控下载：签发短期预签名 URL（调用方负责写审计）"""
        row = await self._get(session, attachment_id)
        url = await TenantMinioStorage.get_presigned_url(HR_BUCKET, row.file_url)
        return {"file_name": row.file_name, "url": url}

    async def delete_attachment(self, session: AsyncSession, attachment_id: str) -> None:
        row = await self._get(session, attachment_id)
        await TenantMinioStorage.delete(HR_BUCKET, row.file_url)
        await session.delete(row)
        await session.flush()
        _logger.info(f"附件删除: {attachment_id}")

    async def _get(self, session: AsyncSession, attachment_id: str) -> EmployeeAttachment:
        row = await session.get(EmployeeAttachment, attachment_id)
        if not row:
            raise NotFoundError(f"附件 {attachment_id} 不存在")
        return row


attachment_service = AttachmentService()
