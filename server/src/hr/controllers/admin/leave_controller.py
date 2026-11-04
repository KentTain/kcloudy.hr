"""假勤管理控制器（假期类型 / 请假审批 / 假期余额）"""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.clients.iam_client import get_iam_client
from framework.common.response import ApiResponse
from framework.database import skip_owner_filter
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.models import Employee, LeaveRequest, LeaveType
from hr.schemas.leave import (
    LeaveBalanceAdjust,
    LeaveRejectRequest,
    LeaveRequestCreate,
    LeaveTransferRequest,
    LeaveTypeCreate,
    LeaveTypeUpdate,
)
from hr.services.leave_request_service import leave_request_service
from hr.services.leave_service import leave_service

router = APIRouter()


# ── 假期类型 ──


@router.get("/leave/types")
async def list_leave_types(
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:leave:read")),
):
    result = await leave_service.list_types(
        session, status=status, page=page, page_size=page_size
    )
    return ApiResponse.paginated(
        data=result["items"], total=result["total"], page=page, page_size=page_size
    )


@router.post("/leave/types")
async def create_leave_type(
    data: LeaveTypeCreate,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:leave:write")),
):
    leave_type = await leave_service.create_type(session, data)
    return ApiResponse.success(data=leave_service.to_type_response(leave_type))


@router.put("/leave/types/{type_id}")
async def update_leave_type(
    type_id: str,
    data: LeaveTypeUpdate,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:leave:write")),
):
    leave_type = await leave_service.update_type(session, type_id, data)
    return ApiResponse.success(data=leave_service.to_type_response(leave_type))


@router.delete("/leave/types/{type_id}")
async def delete_leave_type(
    type_id: str,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:leave:write")),
):
    await leave_service.delete_type(session, type_id)
    return ApiResponse.success(msg="删除成功")


# ── 请假审批 ──


@router.get("/leave/requests")
async def list_leave_requests(
    status: str | None = None,
    leave_type_id: str | None = None,
    org_id: str | None = None,
    keyword: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:leave:read")),
):
    # 管理端全量视角（功能权限已把关），豁免数据归属裁剪
    with skip_owner_filter():
        result = await leave_request_service.list_requests(
            session,
            status=status,
            leave_type_id=leave_type_id,
            org_id=org_id,
            keyword=keyword,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )
    return ApiResponse.paginated(
        data=result["items"], total=result["total"], page=page, page_size=page_size
    )


@router.post("/leave/requests/{request_id}/approve")
async def approve_leave_request(
    request_id: str,
    operator_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:leave:approve")),
):
    # 管理端全量视角（功能权限已把关），豁免数据归属裁剪
    with skip_owner_filter():
        request = await leave_request_service.approve(
            session, request_id, approver_id=operator_id
        )
    return ApiResponse.success(data=leave_request_service.to_response(request))


@router.post("/leave/requests/{request_id}/reject")
async def reject_leave_request(
    request_id: str,
    data: LeaveRejectRequest,
    operator_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:leave:approve")),
):
    # 管理端全量视角（功能权限已把关），豁免数据归属裁剪
    with skip_owner_filter():
        request = await leave_request_service.reject(
            session, request_id, approver_id=operator_id, comment=data.approve_comment
        )
    return ApiResponse.success(data=leave_request_service.to_response(request))


@router.post("/leave/requests/{request_id}/transfer")
async def transfer_leave_request(
    request_id: str,
    data: LeaveTransferRequest,
    operator_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:leave:transfer")),
):
    """移交业务归属人（owner_id 可变归属；同租户在册校验；before/after 审计留痕）"""
    # 管理端全量视角（功能权限已把关），豁免数据归属裁剪
    with skip_owner_filter():
        existing = await session.get(LeaveRequest, request_id)
        before_owner = existing.owner_id if existing else None
        request = await leave_request_service.transfer(
            session, request_id, new_owner_id=data.owner_id
        )
    await get_iam_client().create_audit_log(
        session,
        business_domain="hr",
        operation_type="transfer",
        resource_type="leave_request",
        resource_name=(request.reason or "")[:32] or request_id,
        resource_id=request_id,
        before_data={"owner_id": before_owner},
        after_data={"owner_id": request.owner_id},
        detail={"operator_id": operator_id},
    )
    return ApiResponse.success(data=leave_request_service.to_response(request))


# ── 假期余额 ──


@router.get("/leave/balances")
async def list_leave_balances(
    year: int | None = None,
    org_id: str | None = None,
    keyword: str | None = None,
    leave_type_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:leave:read")),
):
    result = await leave_service.list_balances(
        session,
        year=year,
        org_id=org_id,
        keyword=keyword,
        leave_type_id=leave_type_id,
        page=page,
        page_size=page_size,
    )
    return ApiResponse.paginated(
        data=result["items"], total=result["total"], page=page, page_size=page_size
    )


@router.put("/leave/balances/{balance_id}")
async def adjust_leave_balance(
    balance_id: str,
    data: LeaveBalanceAdjust,
    operator_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:leave:write")),
):
    balance = await leave_service.adjust_balance(
        session, balance_id, data.total_quota, operator_id=operator_id
    )
    employee = await session.get(Employee, balance.employee_id)
    leave_type = await session.get(LeaveType, balance.leave_type_id)
    return ApiResponse.success(
        data=leave_service.to_balance_response(balance, employee, leave_type)
    )
