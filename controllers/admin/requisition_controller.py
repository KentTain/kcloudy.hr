"""招聘需求控制器 - 管理端

需求 CRUD / 渠道发布与下线 / 三段漏斗统计 / 该需求投递列表。
权限码 hr:requisition:read/write。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.schemas.recruiting import (
    RequisitionCreate,
    RequisitionUpdate,
)
from hr.services.ai_assist_service import ai_assist_service
from hr.services.requisition_service import requisition_service

router = APIRouter()


@router.get("/requisitions")
async def list_requisitions(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    priority: str | None = None,
    org_id: str | None = None,
    keyword: str | None = None,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:requisition:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """需求分页列表（含各渠道发布状态）"""
    items, total = await requisition_service.list_requisitions(
        session,
        page=page,
        page_size=page_size,
        status=status,
        priority=priority,
        org_id=org_id,
        keyword=keyword,
    )
    return ApiResponse.paginated(
        data=[requisition_service.to_response(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/requisitions")
async def create_requisition(
    data: RequisitionCreate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:requisition:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """创建需求（编号自动取号；channels 非空时创建后立即发布）"""
    requisition = await requisition_service.create_requisition(session, data)
    requisition = await requisition_service.get_requisition(session, str(requisition.id))
    return ApiResponse.success(data=requisition_service.to_response(requisition))


@router.get("/requisitions/{requisition_id}")
async def get_requisition(
    requisition_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:requisition:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """需求详情（含发布状态明细）"""
    requisition = await requisition_service.get_requisition(session, requisition_id)
    return ApiResponse.success(data=requisition_service.to_response(requisition))


@router.put("/requisitions/{requisition_id}")
async def update_requisition(
    requisition_id: str,
    data: RequisitionUpdate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:requisition:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """更新需求（已关闭拒绝编辑）"""
    requisition = await requisition_service.update_requisition(session, requisition_id, data)
    return ApiResponse.success(data=requisition_service.to_response(requisition))


@router.put("/requisitions/{requisition_id}/close")
async def close_requisition(
    requisition_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:requisition:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """关闭需求（人工终止，关闭后拒绝投递与流转）"""
    requisition = await requisition_service.close_requisition(session, requisition_id)
    return ApiResponse.success(data=requisition_service.to_response(requisition))


@router.post("/requisitions/{requisition_id}/postings")
async def publish_to_channels(
    requisition_id: str,
    channels: list[str],
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:requisition:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """发布需求到渠道（外部渠道任务化，回写 external_post_id）"""
    postings = await requisition_service.publish_to_channels(
        session, requisition_id, channels
    )
    return ApiResponse.success(data=[str(p.id) for p in postings])


@router.put("/postings/{posting_id}/offline")
async def offline_posting(
    posting_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:requisition:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """下线已发布职位"""
    posting = await requisition_service.offline_posting(session, posting_id)
    return ApiResponse.success(data={"id": str(posting.id), "status": posting.status})


@router.get("/requisitions/{requisition_id}/funnel")
async def get_requisition_funnel(
    requisition_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:requisition:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """需求维度三段漏斗统计"""
    funnel = await requisition_service.get_funnel(session, requisition_id)
    return ApiResponse.success(data=funnel)


@router.get("/recruiting/funnel")
async def get_global_funnel(
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:requisition:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """全局漏斗统计（候选人页统计卡与报表切片共用口径）"""
    funnel = await requisition_service.get_funnel(session, None)
    return ApiResponse.success(data=funnel)


@router.post("/requisitions/{requisition_id}/jd-draft")
async def generate_jd_draft(
    requisition_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:requisition:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """JD 智能生成草稿（即时返回不落库，LLM 失败提示手动填写）"""
    result = await ai_assist_service.generate_jd_draft(session, requisition_id)
    return ApiResponse.success(data=result)
