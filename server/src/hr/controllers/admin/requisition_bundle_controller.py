"""招聘聚合单控制器 - 管理端（流程测试载体）

父=招聘需求、明细=申请（内嵌候选人）、孙=Offer（1:1）；创建/编辑请求体即
父子孙嵌套结构，供接口库导入与表单向导生成三级表单。
权限码复用 hr:requisition:read/write。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.schemas.recruiting import (
    RequisitionBundleCreate,
    RequisitionBundleUpdate,
)
from hr.services.requisition_bundle_service import requisition_bundle_service

router = APIRouter()


@router.get("/requisition-bundles")
async def list_requisition_bundles(
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:requisition:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """聚合单分页列表（需求行 + 申请数/Offer 数）"""
    items, total = await requisition_bundle_service.list_bundles(
        session, page=page, page_size=page_size, keyword=keyword
    )
    return ApiResponse.paginated(data=items, total=total, page=page, page_size=page_size)


@router.post("/requisition-bundles")
async def create_requisition_bundle(
    data: RequisitionBundleCreate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:requisition:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """创建聚合单（需求 + 明细行 + 行内 Offer 三级一次落库）"""
    detail = await requisition_bundle_service.create_bundle(session, data)
    return ApiResponse.success(data=detail)


@router.get("/requisition-bundles/{requisition_id}")
async def get_requisition_bundle(
    requisition_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:requisition:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """聚合详情（父字段 + 申请明细行 + 行内 Offer）"""
    detail = await requisition_bundle_service.get_bundle_detail(session, requisition_id)
    return ApiResponse.success(data=detail)


@router.put("/requisition-bundles/{requisition_id}")
async def update_requisition_bundle(
    requisition_id: str,
    data: RequisitionBundleUpdate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:requisition:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """编辑聚合单（父字段更新 + 明细按行 upsert）"""
    detail = await requisition_bundle_service.update_bundle(session, requisition_id, data)
    return ApiResponse.success(data=detail)
