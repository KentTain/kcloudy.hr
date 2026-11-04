"""员工自助控制器（console：我的档案/薪酬单/目标/绩效/变更申请 + 团队成员）"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from hr.schemas.perf import PerfGoalProgressUpdate
from hr.schemas.self_service import ChangeRequestCreate
from iam.dependencies import get_current_user_id

from hr.services.self_service_service import self_service_service

router = APIRouter()


@router.get("/me/profile")
async def get_my_profile(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    result = await self_service_service.get_profile(session, user_id)
    return ApiResponse.success(data=result)


@router.get("/me/pay-slips")
async def list_my_pay_slips(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    items = await self_service_service.list_pay_slips(session, user_id)
    return ApiResponse.success(data=items)


@router.get("/me/pay-slips/{period}")
async def get_my_pay_slip(
    period: str,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    result = await self_service_service.get_pay_slip(session, user_id, period)
    return ApiResponse.success(data=result)


@router.get("/team/employees")
async def list_team_employees(
    page: int = 1,
    page_size: int = 20,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    result = await self_service_service.list_team_employees(
        session, user_id, page=page, page_size=page_size
    )
    return ApiResponse.paginated(
        data=result["items"], total=result["total"], page=page, page_size=page_size
    )


@router.get("/me/goals")
async def get_my_goals(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    items = await self_service_service.list_my_goals(session, user_id)
    return ApiResponse.success(data=items)


@router.put("/me/goals/{goal_id}/progress")
async def update_my_goal_progress(
    goal_id: str,
    data: PerfGoalProgressUpdate,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    goal = await self_service_service.update_my_goal_progress(
        session, user_id, goal_id, progress=data.progress, actual_value=data.actual_value
    )
    return ApiResponse.success(
        data={"id": str(goal.id), "progress": goal.progress, "actual_value": goal.actual_value}
    )


@router.get("/me/reviews")
async def get_my_reviews(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    items = await self_service_service.list_my_reviews(session, user_id)
    return ApiResponse.success(data=items)


@router.get("/me/profile/change-requests")
async def list_my_change_requests(
    page: int = 1,
    page_size: int = 20,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    result = await self_service_service.list_my_change_requests(
        session, user_id, page=page, page_size=page_size
    )
    return ApiResponse.paginated(
        data=result["items"], total=result["total"], page=page, page_size=page_size
    )


@router.post("/me/profile/change-requests")
async def submit_change_request(
    data: ChangeRequestCreate,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    result = await self_service_service.submit_change_request(
        session, user_id, title=data.title, changes=[item.model_dump() for item in data.changes]
    )
    return ApiResponse.success(data=result)


@router.post("/me/profile/change-requests/{request_id}/cancel")
async def cancel_my_change_request(
    request_id: str,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    await self_service_service.cancel_change_request(session, user_id, request_id)
    return ApiResponse.success(data={"id": request_id, "status": "cancelled"})
