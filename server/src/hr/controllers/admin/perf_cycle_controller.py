"""考核周期控制器（周期 CRUD/状态机推进/分布 + 目标整批提交/进度）"""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.clients.iam_client import get_iam_client
from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.schemas.perf import (
    PerfCycleCreate,
    PerfCycleUpdate,
    PerfDistributionResponse,
    PerfGoalBatchCreate,
    PerfGoalProgressUpdate,
    PerfGoalUpdate,
)
from hr.services.perf_cycle_service import perf_cycle_service

router = APIRouter()


@router.get("/perf-cycles")
async def list_perf_cycles(
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_cycle:read")),
):
    result = await perf_cycle_service.list_cycles(
        session,
        status=status,
        date_from=date_from,
        date_to=date_to,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return ApiResponse.paginated(
        data=result["items"], total=result["total"], page=page, page_size=page_size
    )


@router.post("/perf-cycles")
async def create_perf_cycle(
    data: PerfCycleCreate,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_cycle:write")),
):
    cycle = await perf_cycle_service.create_cycle(
        session, name=data.name, start_date=data.start_date, end_date=data.end_date
    )
    return ApiResponse.success(data=perf_cycle_service.to_response(cycle))


@router.get("/perf-cycles/{cycle_id}")
async def get_perf_cycle(
    cycle_id: str,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_cycle:read")),
):
    return ApiResponse.success(data=await perf_cycle_service.get_cycle(session, cycle_id))


@router.put("/perf-cycles/{cycle_id}")
async def update_perf_cycle(
    cycle_id: str,
    data: PerfCycleUpdate,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_cycle:write")),
):
    cycle = await perf_cycle_service.update_cycle(
        session,
        cycle_id,
        name=data.name,
        start_date=data.start_date,
        end_date=data.end_date,
    )
    return ApiResponse.success(data=perf_cycle_service.to_response(cycle))


@router.delete("/perf-cycles/{cycle_id}")
async def delete_perf_cycle(
    cycle_id: str,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_cycle:delete")),
):
    await perf_cycle_service.delete_cycle(session, cycle_id)
    return ApiResponse.success(msg="删除成功")


@router.post("/perf-cycles/{cycle_id}/activate")
async def activate_perf_cycle(
    cycle_id: str,
    operator_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_cycle:write")),
):
    """激活（开放目标制定；写审计）"""
    cycle = await perf_cycle_service.transition(session, cycle_id, action="activate")
    await _audit_transition(session, cycle, "activate", operator_id)
    return ApiResponse.success(data=perf_cycle_service.to_response(cycle))


@router.post("/perf-cycles/{cycle_id}/scoring")
async def scoring_perf_cycle(
    cycle_id: str,
    operator_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_cycle:write")),
):
    """进入评分（写审计）"""
    cycle = await perf_cycle_service.transition(session, cycle_id, action="scoring")
    await _audit_transition(session, cycle, "scoring", operator_id)
    return ApiResponse.success(data=perf_cycle_service.to_response(cycle))


@router.post("/perf-cycles/{cycle_id}/calibrating")
async def calibrating_perf_cycle(
    cycle_id: str,
    operator_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_cycle:write")),
):
    """进入校准（写审计）"""
    cycle = await perf_cycle_service.transition(session, cycle_id, action="calibrating")
    await _audit_transition(session, cycle, "calibrating", operator_id)
    return ApiResponse.success(data=perf_cycle_service.to_response(cycle))


@router.post("/perf-cycles/{cycle_id}/close")
async def close_perf_cycle(
    cycle_id: str,
    operator_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_cycle:write")),
):
    """收口（锁定结果，评级系数写入见收口链路；写审计）"""
    cycle = await perf_cycle_service.transition(session, cycle_id, action="close")
    await _audit_transition(session, cycle, "close", operator_id)
    return ApiResponse.success(data=perf_cycle_service.to_response(cycle))


@router.get("/perf-cycles/{cycle_id}/distribution")
async def get_perf_distribution(
    cycle_id: str,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_cycle:read")),
):
    """评级分布（校准参考；口径 calibrated_rating 优先回退 rating）"""
    data = await perf_cycle_service.distribution(session, cycle_id)
    return ApiResponse.success(data=PerfDistributionResponse(**data))


@router.get("/perf-goals")
async def list_perf_goals(
    cycle_id: str | None = None,
    employee_id: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_goal:read")),
):
    result = await perf_cycle_service.list_goals(
        session,
        cycle_id=cycle_id,
        employee_id=employee_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    return ApiResponse.paginated(
        data=result["items"], total=result["total"], page=page, page_size=page_size
    )


@router.post("/perf-goals")
async def submit_perf_goals(
    data: PerfGoalBatchCreate,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_goal:write")),
):
    """目标整批提交（权重合计须恰好 100；同员工同周期替换未完成目标）"""
    goals = await perf_cycle_service.submit_goals(
        session,
        cycle_id=data.cycle_id,
        employee_id=data.employee_id,
        goals=[item.model_dump() for item in data.goals],
    )
    return ApiResponse.success(
        data=[perf_cycle_service.goal_to_response(goal) for goal in goals]
    )


@router.put("/perf-goals/{goal_id}")
async def update_perf_goal(
    goal_id: str,
    data: PerfGoalUpdate,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_goal:write")),
):
    goal = await perf_cycle_service.update_goal(
        session,
        goal_id,
        name=data.name,
        weight=data.weight,
        target_value=data.target_value,
    )
    return ApiResponse.success(data=perf_cycle_service.goal_to_response(goal))


@router.put("/perf-goals/{goal_id}/progress")
async def update_perf_goal_progress(
    goal_id: str,
    data: PerfGoalProgressUpdate,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_goal:write")),
):
    goal = await perf_cycle_service.update_goal_progress(
        session, goal_id, progress=data.progress, actual_value=data.actual_value
    )
    return ApiResponse.success(data=perf_cycle_service.goal_to_response(goal))


@router.delete("/perf-goals/{goal_id}")
async def delete_perf_goal(
    goal_id: str,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_goal:delete")),
):
    await perf_cycle_service.delete_goal(session, goal_id)
    return ApiResponse.success(msg="删除成功")


async def _audit_transition(
    session: AsyncSession, cycle, action: str, operator_id: str
) -> None:
    await get_iam_client().create_audit_log(
        session,
        business_domain="hr",
        operation_type=action,
        resource_type="perf_cycle",
        resource_name=cycle.name,
        resource_id=str(cycle.id),
        detail={"operator_id": operator_id, "status": cycle.status},
    )
