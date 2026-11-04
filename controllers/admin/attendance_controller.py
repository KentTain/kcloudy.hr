"""考勤管理控制器（记录列表 / 总览统计 / Excel 与 AI 导入）"""

from datetime import date

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.services.attendance_import_service import attendance_import_service
from hr.services.attendance_service import attendance_service

router = APIRouter()


@router.get("/attendance/records")
async def list_attendance_records(
    date_from: date | None = None,
    date_to: date | None = None,
    org_id: str | None = None,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:attendance:read")),
):
    result = await attendance_service.list_records(
        session,
        date_from=date_from,
        date_to=date_to,
        org_id=org_id,
        keyword=keyword,
        status=status,
        page=page,
        page_size=page_size,
    )
    return ApiResponse.paginated(
        data=result["items"], total=result["total"], page=page, page_size=page_size
    )


@router.get("/attendance/stats")
async def get_attendance_stats(
    date_from: date | None = None,
    date_to: date | None = None,
    org_id: str | None = None,
    keyword: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:attendance:read")),
):
    stats = await attendance_service.get_stats(
        session, date_from=date_from, date_to=date_to, org_id=org_id, keyword=keyword
    )
    return ApiResponse.success(data=stats)


@router.get("/attendance/import-template")
async def download_import_template(
    _: None = Depends(require_permission("hr:attendance:import")),
):
    content = attendance_import_service.build_template()
    return ApiResponse.success(
        data={
            "filename": "考勤导入模板.xlsx",
            "content_base64": attendance_import_service.encode_content(content),
        }
    )


@router.post("/attendance/import")
async def import_attendance(
    file: UploadFile = File(...),
    dry_run: bool = Form(False),
    session: AsyncSession = Depends(get_db_session),
    operator_id: str = Depends(get_current_user_id),
    _: None = Depends(require_permission("hr:attendance:import")),
):
    content = await file.read()
    result = await attendance_import_service.import_excel(
        session,
        content,
        file.filename or "attendance.xlsx",
        dry_run=dry_run,
        operator_id=operator_id,
    )
    return ApiResponse.success(data=result)


@router.post("/attendance/ai-imports")
async def create_ai_import_batch(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
    operator_id: str = Depends(get_current_user_id),
    _: None = Depends(require_permission("hr:attendance:import")),
):
    content = await file.read()
    result = await attendance_import_service.create_ai_batch(
        session,
        content,
        file.filename or "attendance.xlsx",
        operator_id=operator_id,
    )
    return ApiResponse.success(data=result)


@router.get("/attendance/ai-imports/{batch_id}")
async def get_ai_import_batch(
    batch_id: str,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:attendance:import")),
):
    batch = await attendance_import_service.get_batch(session, batch_id)
    return ApiResponse.success(data=batch)


@router.post("/attendance/ai-imports/{batch_id}/confirm")
async def confirm_ai_import_batch(
    batch_id: str,
    row_indexes: list[int] = Form(...),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:attendance:import")),
):
    result = await attendance_import_service.confirm_batch(
        session, batch_id, row_indexes
    )
    return ApiResponse.success(data=result)


@router.post("/attendance/ai-imports/{batch_id}/retry")
async def retry_ai_import_batch(
    batch_id: str,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:attendance:import")),
):
    result = await attendance_import_service.retry_batch(session, batch_id)
    return ApiResponse.success(data=result)


@router.get("/attendance/ai-batches")
async def list_ai_import_batches(
    page: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:attendance:import")),
):
    """AI 导入批次列表（时间倒序，供弹窗回看历史批次）"""
    result = await attendance_import_service.list_ai_batches(
        session, page=page, page_size=page_size
    )
    return ApiResponse.success(data=result)


@router.get("/attendance/ai-batches/{batch_id}/failures")
async def export_ai_batch_failures(
    batch_id: str,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:attendance:import")),
):
    """AI 导入失败行明细下载（xlsx，行号与导入校验一致）"""
    filename, content = await attendance_import_service.export_failure_rows(
        session, batch_id
    )
    return ApiResponse.success(
        data={
            "filename": filename,
            "content_base64": attendance_import_service.encode_content(content),
        }
    )
