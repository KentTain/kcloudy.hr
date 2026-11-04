"""面试控制器 - 管理端

安排面试（轮次自动 +1）/ 周视图按日分组 / 结论反馈与改期（通知面试官）/
AI 纪要任务化提交（消费者回写）/ 智能追问建议。权限码 hr:interview:read/write。
"""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.schemas.recruiting import InterviewCreate, InterviewUpdate
from hr.services.ai_assist_service import ai_assist_service
from hr.services.interview_service import interview_service

router = APIRouter()


@router.post("/applications/{application_id}/interviews")
async def create_interview(
    application_id: str,
    data: InterviewCreate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:interview:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """安排面试（轮次自动 +1）"""
    data.application_id = application_id
    interview = await interview_service.create_interview(session, data)
    return ApiResponse.success(data=interview_service.to_response(interview))


@router.get("/interviews/weekly")
async def get_weekly_interviews(
    start_date: date | None = None,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:interview:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """周视图：起始于 start_date（缺省今日）的 7 天面试按日分组"""
    weekly = await interview_service.get_weekly(session, start_date)
    return ApiResponse.success(data=weekly)


@router.get("/interviews/{interview_id}")
async def get_interview_detail(
    interview_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:interview:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """面试详情（纪要任务提交后前端轮询 ai_summary 就绪）"""
    interview = await interview_service.get_interview(session, interview_id)
    return ApiResponse.success(data=interview_service.to_response(interview))


@router.put("/interviews/{interview_id}")
async def update_interview(
    interview_id: str,
    data: InterviewUpdate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:interview:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """面试结论/反馈/改期（改期通知面试官；通过自动流转拟录用）"""
    interview = await interview_service.update_interview(session, interview_id, data)
    return ApiResponse.success(data=interview_service.to_response(interview))


@router.post("/interviews/{interview_id}/ai-summary")
async def submit_ai_summary(
    interview_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:interview:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """提交 AI 纪要任务（异步生成，任务管理页可视；进行中重复提交幂等）"""
    result = await interview_service.submit_summary_task(session, interview_id)
    return ApiResponse.success(data=result)


@router.post("/interviews/{interview_id}/followup-questions")
async def followup_questions(
    interview_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:interview:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """面试智能追问建议（即时生成不落库，失败走手动填写兜底）"""
    result = await ai_assist_service.generate_followup_questions(session, interview_id)
    return ApiResponse.success(data=result)
