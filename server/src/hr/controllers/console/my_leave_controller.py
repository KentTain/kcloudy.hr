"""我的假期控制器（console：本人余额 / 请假申请与撤销）"""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id

from hr.schemas.leave import LeaveRequestCreate
from hr.services.employee_service import employee_service
from hr.services.leave_request_service import leave_request_service
from hr.services.leave_service import leave_service

router = APIRouter()


@router.get("/me/leave-balances")
async def list_my_leave_balances(
    year: int | None = None,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    employee = await employee_service.get_employee_by_user_id(session, user_id)
    year = year or date.today().year
    leave_types = await leave_service.list_enabled_types(session)
    items = []
    for leave_type in leave_types:
        balance = await leave_service.get_or_create_balance(
            session, str(employee.id), leave_type, year
        )
        items.append(
            leave_service.to_balance_response(balance, employee, leave_type)
        )
    return ApiResponse.success(data=items)


@router.get("/me/leave-requests")
async def list_my_leave_requests(
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    employee = await employee_service.get_employee_by_user_id(session, user_id)
    result = await leave_request_service.list_requests(
        session,
        status=status,
        employee_id=str(employee.id),
        page=page,
        page_size=page_size,
    )
    return ApiResponse.paginated(
        data=result["items"], total=result["total"], page=page, page_size=page_size
    )


@router.post("/me/leave-requests")
async def submit_my_leave_request(
    data: LeaveRequestCreate,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    employee = await employee_service.get_employee_by_user_id(session, user_id)
    request = await leave_request_service.submit_request(
        session, str(employee.id), data
    )
    return ApiResponse.success(data=leave_request_service.to_response(request))


@router.post("/me/leave-requests/{request_id}/cancel")
async def cancel_my_leave_request(
    request_id: str,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    employee = await employee_service.get_employee_by_user_id(session, user_id)
    request = await leave_request_service.cancel_request(
        session, request_id, operator_employee_id=str(employee.id)
    )
    return ApiResponse.success(data=leave_request_service.to_response(request))
