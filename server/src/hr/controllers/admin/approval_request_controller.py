"""审批中心控制器（审批请求列表 / 详情 / 通过 / 驳回）"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.clients.iam_client import get_iam_client
from framework.common.response import ApiResponse
from framework.database import skip_owner_filter
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.models import ApprovalRequest
from hr.schemas.approval import ApprovalRejectRequest, ApprovalTransferRequest
from hr.services.approval_service import approval_service

router = APIRouter()


@router.get("/approval-requests")
async def list_approval_requests(
    biz_type: str | None = None,
    status: str | None = None,
    applicant_employee_id: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:approval:read")),
):
    # 管理端全量视角（功能权限已把关），豁免数据归属裁剪
    with skip_owner_filter():
        result = await approval_service.list_requests(
            session,
            biz_type=biz_type,
            status=status,
            applicant_employee_id=applicant_employee_id,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
    return ApiResponse.paginated(
        data=result["items"], total=result["total"], page=page, page_size=page_size
    )


@router.get("/approval-requests/{request_id}")
async def get_approval_request(
    request_id: str,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:approval:read")),
):
    # 管理端全量视角（功能权限已把关），豁免数据归属裁剪
    with skip_owner_filter():
        detail = await approval_service.get_detail(session, request_id)
    return ApiResponse.success(data=detail)


@router.post("/approval-requests/{request_id}/approve")
async def approve_approval_request(
    request_id: str,
    operator_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:approval:approve")),
):
    """审批通过（业务变更与状态更新同事务；写审计）"""
    # 管理端全量视角（功能权限已把关），豁免数据归属裁剪
    with skip_owner_filter():
        request = await approval_service.approve(
            session, request_id, approver_id=operator_id
        )
    await get_iam_client().create_audit_log(
        session,
        business_domain="hr",
        operation_type="approve",
        resource_type="approval_request",
        resource_name=request.title,
        resource_id=request_id,
        detail={"operator_id": operator_id, "biz_type": request.biz_type},
    )
    return ApiResponse.success(data=approval_service.to_response(request))


@router.post("/approval-requests/{request_id}/reject")
async def reject_approval_request(
    request_id: str,
    data: ApprovalRejectRequest,
    operator_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:approval:approve")),
):
    """审批驳回（意见必填；写审计）"""
    # 管理端全量视角（功能权限已把关），豁免数据归属裁剪
    with skip_owner_filter():
        request = await approval_service.reject(
            session, request_id, approver_id=operator_id, comment=data.approve_comment
        )
    await get_iam_client().create_audit_log(
        session,
        business_domain="hr",
        operation_type="reject",
        resource_type="approval_request",
        resource_name=request.title,
        resource_id=request_id,
        detail={"operator_id": operator_id, "biz_type": request.biz_type},
    )
    return ApiResponse.success(data=approval_service.to_response(request))


@router.post("/approval-requests/{request_id}/transfer")
async def transfer_approval_request(
    request_id: str,
    data: ApprovalTransferRequest,
    operator_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:approval:transfer")),
):
    """移交业务归属人（owner_id 可变归属；同租户在册校验；before/after 审计留痕）"""
    # 管理端全量视角（功能权限已把关），豁免数据归属裁剪
    with skip_owner_filter():
        existing = await session.get(ApprovalRequest, request_id)
        before_owner = existing.owner_id if existing else None
        request = await approval_service.transfer_request(
            session, request_id, new_owner_id=data.owner_id
        )
    await get_iam_client().create_audit_log(
        session,
        business_domain="hr",
        operation_type="transfer",
        resource_type="approval_request",
        resource_name=request.title,
        resource_id=request_id,
        before_data={"owner_id": before_owner},
        after_data={"owner_id": request.owner_id},
        detail={"operator_id": operator_id, "biz_type": request.biz_type},
    )
    return ApiResponse.success(data=approval_service.to_response(request))
