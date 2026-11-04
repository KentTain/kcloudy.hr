"""Offer 控制器 - 管理端

定薪快照创建 / 发送 / 接受 / 拒绝 / 入职转化建档。
权限码 hr:offer:read/write。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.schemas.recruiting import OfferCreate, OfferOnboardCreate
from hr.services.offer_service import offer_service

router = APIRouter()


@router.post("/offers")
async def create_offer(
    data: OfferCreate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:offer:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """创建 Offer 单（薪酬方案快照；申请须为拟录用）"""
    offer = await offer_service.create_offer(session, data)
    return ApiResponse.success(data=offer_service.to_response(offer))


@router.get("/offers/{offer_id}")
async def get_offer(
    offer_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:offer:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """Offer 详情"""
    offer = await offer_service.get_offer(session, offer_id)
    return ApiResponse.success(data=offer_service.to_response(offer))


@router.get("/applications/{application_id}/offer")
async def get_application_offer(
    application_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:offer:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """申请维度查 Offer（卡片接受/拒绝/入职操作入口；未发返回 null）"""
    offer = await offer_service.get_offer_by_application(session, application_id)
    return ApiResponse.success(
        data=offer_service.to_response(offer) if offer else None
    )


@router.put("/offers/{offer_id}/send")
async def send_offer(
    offer_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:offer:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """发送 Offer（申请流转至已发 Offer）"""
    offer = await offer_service.send_offer(session, offer_id)
    return ApiResponse.success(data=offer_service.to_response(offer))


@router.post("/offers/{offer_id}/accept")
async def accept_offer(
    offer_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:offer:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """候选人接受 Offer（申请流转至待入职）"""
    offer = await offer_service.accept_offer(session, offer_id)
    return ApiResponse.success(data=offer_service.to_response(offer))


@router.post("/offers/{offer_id}/reject")
async def reject_offer(
    offer_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:offer:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """候选人拒绝 Offer（申请淘汰）"""
    offer = await offer_service.reject_offer(session, offer_id)
    return ApiResponse.success(data=offer_service.to_response(offer))


@router.post("/offers/{offer_id}/onboard")
async def onboard(
    offer_id: str,
    data: OfferOnboardCreate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:offer:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """入职转化建档（员工自动取号 + hire 流水；需求 filled_count 联动）"""
    result = await offer_service.onboard(
        session,
        offer_id,
        hire_date=data.hire_date,
        position_id=data.position_id,
    )
    return ApiResponse.success(data=result)
