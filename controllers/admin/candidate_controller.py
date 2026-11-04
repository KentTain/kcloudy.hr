"""候选人控制器 - 管理端

候选人卡片流 / 手工录入 / 详情聚合 / 编辑删除 / 黑名单 / 重复档合并 /
AI 简历解析触发 / 投递漏斗流转。权限码 hr:candidate:read/write/merge。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.models import Candidate, CandidateApplication, JobRequisition
from hr.schemas.recruiting import (
    ApplicationResponse,
    CandidateCreate,
    CandidateResponse,
    CandidateUpdate,
    StageUpdate,
)
from hr.services.candidate_service import candidate_service

router = APIRouter()


def _mask_phone(phone: str | None) -> str | None:
    """列表卡片流手机号脱敏回显（保留前 3 后 4）。"""
    if not phone or len(phone) < 8:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"


def _candidate_to_response(
    candidate: Candidate, *, mask_phone: bool = False
) -> CandidateResponse:
    return CandidateResponse(
        id=str(candidate.id),
        name=candidate.name,
        phone=_mask_phone(candidate.phone) if mask_phone else candidate.phone,
        email=candidate.email,
        source_channel=candidate.source_channel,
        is_blacklist=candidate.is_blacklist,
        profile=candidate.profile,
        resume_file=candidate.resume_file,
    )


def _application_to_response(
    application: CandidateApplication,
    candidate: Candidate | None = None,
    requisition: JobRequisition | None = None,
) -> ApplicationResponse:
    return ApplicationResponse(
        id=str(application.id),
        candidate_id=str(application.candidate_id),
        candidate_name=candidate.name if candidate else None,
        requisition_id=str(application.requisition_id),
        requisition_title=requisition.title if requisition else None,
        stage=application.stage,
        stage_history=application.stage_history or [],
        match_score=float(application.match_score)
        if application.match_score is not None
        else None,
        apply_time=application.apply_time,
        employee_id=application.employee_id,
    )


@router.get("/candidates")
async def list_candidates(
    page: int = 1,
    page_size: int = 20,
    stage: str | None = None,
    channel: str | None = None,
    requisition_id: str | None = None,
    keyword: str | None = None,
    include_blacklist: bool = False,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:candidate:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """投递卡片流分页（黑名单默认隐藏，keyword 命中姓名/手机/邮箱）"""
    rows, total = await candidate_service.list_applications(
        session,
        page=page,
        page_size=page_size,
        stage=stage,
        channel=channel,
        requisition_id=requisition_id,
        keyword=keyword,
        include_blacklist=include_blacklist,
    )
    return ApiResponse.paginated(
        data=[
            _application_to_response(application, candidate, requisition)
            for application, candidate, requisition in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/candidates")
async def create_candidate(
    data: CandidateCreate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:candidate:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """手工录入候选人（关联需求时同步产生待初筛投递）"""
    candidate, application = await candidate_service.create_candidate(
        session,
        name=data.name,
        phone=data.phone,
        email=data.email,
        source_channel=data.source_channel,
        requisition_id=data.requisition_id,
    )
    payload = _candidate_to_response(candidate).model_dump()
    if application is not None:
        payload["application"] = _application_to_response(application).model_dump()
    return ApiResponse.success(data=payload)


@router.get("/candidates/{candidate_id}")
async def get_candidate(
    candidate_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:candidate:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """候选人详情（主档 + 全部投递申请）"""
    candidate = await candidate_service.get_candidate(session, candidate_id)
    applications = await candidate_service.list_candidate_applications(
        session, candidate_id
    )
    payload = _candidate_to_response(candidate).model_dump()
    payload["applications"] = [
        _application_to_response(a).model_dump() for a in applications
    ]
    return ApiResponse.success(data=payload)


@router.put("/candidates/{candidate_id}")
async def update_candidate(
    candidate_id: str,
    data: CandidateUpdate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:candidate:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """编辑候选人主档"""
    candidate = await candidate_service.update_candidate(
        session,
        candidate_id,
        data.model_dump(exclude_unset=True, exclude_none=True),
    )
    return ApiResponse.success(data=_candidate_to_response(candidate))


@router.delete("/candidates/{candidate_id}")
async def delete_candidate(
    candidate_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:candidate:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """删除候选人（存在进行中投递时拒绝）"""
    await candidate_service.delete_candidate(session, candidate_id)
    return ApiResponse.success(message="删除成功")


@router.post("/candidates/{candidate_id}/resume/parse")
async def trigger_resume_parse(
    candidate_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:candidate:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """触发 AI 简历解析任务（异步回写 profile，失败可重试）"""
    candidate_id = await candidate_service.trigger_resume_parse(session, candidate_id)
    return ApiResponse.success(
        data={"candidate_id": candidate_id, "task_type": "hr_resume_parse"}
    )


@router.post("/candidates/{source_id}/merge/{target_id}")
async def merge_candidates(
    source_id: str,
    target_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:candidate:merge")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """重复档合并：source 投递/面试归并到 target 后删除 source"""
    merged = await candidate_service.merge_candidates(session, source_id, target_id)
    return ApiResponse.success(data={"merged_applications": merged})


@router.get("/candidates/{candidate_id}/merge-suggestions")
async def get_merge_suggestions(
    candidate_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:candidate:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """疑似重复档建议（手机/邮箱命中；供合并弹窗直选目标）"""
    suggestions = await candidate_service.merge_suggestions(session, candidate_id)
    return ApiResponse.success(data=suggestions)


@router.post("/candidates/{candidate_id}/blacklist")
async def add_blacklist(
    candidate_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:candidate:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """加入黑名单（默认筛选不再展示）"""
    candidate = await candidate_service.set_blacklist(session, candidate_id, True)
    return ApiResponse.success(data=_candidate_to_response(candidate))


@router.post("/candidates/{candidate_id}/unblacklist")
async def remove_blacklist(
    candidate_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:candidate:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """移出黑名单"""
    candidate = await candidate_service.set_blacklist(session, candidate_id, False)
    return ApiResponse.success(data=_candidate_to_response(candidate))


@router.get("/applications/{application_id}")
async def get_application(
    application_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:candidate:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """投递详情（含流转史与面试轮次数）"""
    application = await candidate_service.get_application(session, application_id)
    candidate = await candidate_service.get_candidate(
        session, str(application.candidate_id)
    )
    interview_count = await candidate_service.count_application_interviews(
        session, str(application.id)
    )
    payload = _application_to_response(application, candidate).model_dump()
    payload["interview_count"] = interview_count
    return ApiResponse.success(data=payload)


@router.put("/applications/{application_id}/stage")
async def change_stage(
    application_id: str,
    data: StageUpdate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:candidate:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """漏斗阶段流转（状态机校验；onboarded 联动需求 filled_count）"""
    application = await candidate_service.change_stage(
        session, application_id, data.stage, remark=data.remark
    )
    return ApiResponse.success(data=_application_to_response(application))
