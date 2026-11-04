"""面试服务：快捷安排（轮次自动+1）/ 周视图聚合 / 面试评价与改期通知 / AI 纪要"""

from datetime import UTC, date, datetime, timedelta

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, NotFoundError
from framework.common.ctx import get_tenant_id
from framework.notification.dispatcher import notify

from hr.integration.llm_client import llm_chat
from hr.models import Candidate, CandidateApplication, Interview, JobRequisition
from hr.schemas.recruiting import InterviewCreate, InterviewResponse, InterviewUpdate
from hr.services.candidate_service import candidate_service

_logger = logger.bind(name=__name__)

AI_SUMMARY_TASK_TYPE = "hr_interview_summary"
AI_SUMMARY_QUEUE = "hr-interview-summary"

_WEEK_WINDOW_DAYS = 7


def _now() -> datetime:
    return datetime.now(UTC)


class InterviewService:
    """面试业务"""

    # ── 安排 / 查询 ──

    async def create_interview(
        self, session: AsyncSession, data: InterviewCreate
    ) -> Interview:
        """安排面试：轮次自动 +1（同申请同轮唯一约束兜重）。"""
        application = await candidate_service.get_application(
            session, data.application_id
        )
        if application.stage in ("rejected", "withdrawn", "onboarded"):
            raise BadRequestError(f"投递处于终态 {application.stage}，不可安排面试")

        max_round = (
            await session.execute(
                select(func.max(Interview.round)).where(
                    Interview.application_id == data.application_id
                )
            )
        ).scalar_one()
        interview = Interview(
            tenant_id=get_tenant_id(),
            application_id=data.application_id,
            round=(max_round or 0) + 1,
            interviewer_id=data.interviewer_id,
            scheduled_at=data.scheduled_at,
            interview_form=data.interview_form,
        )
        session.add(interview)
        await session.flush()
        return interview

    async def get_interview(self, session: AsyncSession, interview_id: str) -> Interview:
        interview = await session.get(Interview, interview_id)
        if not interview:
            raise NotFoundError(f"面试 {interview_id} 不存在")
        return interview

    async def get_weekly(
        self, session: AsyncSession, start: date | None = None
    ) -> dict:
        """周视图：起始于 start（缺省今日）的 7 天面试，按日分组。"""
        start = start or date.today()
        end = start + timedelta(days=_WEEK_WINDOW_DAYS)
        start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)
        end_dt = datetime(end.year, end.month, end.day, tzinfo=UTC)

        result = await session.execute(
            select(Interview, CandidateApplication, Candidate, JobRequisition)
            .join(
                CandidateApplication,
                Interview.application_id == CandidateApplication.id,
            )
            .join(Candidate, CandidateApplication.candidate_id == Candidate.id)
            .join(
                JobRequisition,
                CandidateApplication.requisition_id == JobRequisition.id,
            )
            .where(
                Interview.scheduled_at >= start_dt,
                Interview.scheduled_at < end_dt,
            )
            .order_by(Interview.scheduled_at)
        )
        days: dict[str, list[dict]] = {}
        for offset in range(_WEEK_WINDOW_DAYS):
            day = start + timedelta(days=offset)
            days[day.isoformat()] = []
        for interview, application, candidate, requisition in result.all():
            key = interview.scheduled_at.date().isoformat()
            days.setdefault(key, []).append(
                {
                    "id": str(interview.id),
                    "application_id": str(application.id),
                    "candidate_name": candidate.name,
                    "requisition_title": requisition.title,
                    "round": interview.round,
                    "interviewer_id": str(interview.interviewer_id),
                    "scheduled_at": interview.scheduled_at,
                    "interview_form": interview.interview_form,
                    "result": interview.result,
                }
            )
        return {"start": start.isoformat(), "days": days}

    # ── 评价 / 改期 ──

    async def update_interview(
        self, session: AsyncSession, interview_id: str, data: InterviewUpdate
    ) -> Interview:
        """面试结论/反馈/改期：改期通知面试官；通过自动流转「拟录用」。"""
        interview = await self.get_interview(session, interview_id)
        updates = data.model_dump(exclude_unset=True, exclude_none=True)

        rescheduled = (
            "scheduled_at" in updates
            and updates["scheduled_at"] != interview.scheduled_at
        )
        for field, value in updates.items():
            setattr(interview, field, value)

        if rescheduled:
            await self._notify_reschedule(session, interview)

        if interview.result == "pass":
            await self._promote_on_pass(session, interview)
        return interview

    async def _notify_reschedule(
        self, session: AsyncSession, interview: Interview
    ) -> None:
        """改期通知面试官（站内信）；失败不阻断改期。"""
        try:
            from hr.services.employee_service import employee_service

            interviewer = await employee_service.get_employee(
                session, str(interview.interviewer_id)
            )
            if not interviewer.user_id:
                return
            await notify(
                session=session,
                notification_type="hr_interview_rescheduled",
                recipients=[str(interviewer.user_id)],
                title="面试改期提醒",
                content=f"您有一场面试已改期至 {interview.scheduled_at:%Y-%m-%d %H:%M}（第 {interview.round} 轮），请留意安排。",
                link="/hr/interviews",
            )
        except Exception as exc:  # noqa: BLE001 — 通知失败不阻断
            _logger.warning(f"面试改期通知失败 interview={interview.id}: {exc}")

    async def _promote_on_pass(
        self, session: AsyncSession, interview: Interview
    ) -> None:
        """结论通过自动流转「拟录用」（interviewing/screening_passed → pre_hire）。

        流转失败（需求关闭/满编等）不阻断结论保存。
        """
        result = await session.execute(
            select(CandidateApplication).where(
                CandidateApplication.id == interview.application_id
            )
        )
        application = result.scalar_one_or_none()
        if application is None or application.stage not in (
            "screening_passed",
            "interviewing",
        ):
            return
        try:
            await candidate_service.change_stage(
                session, str(application.id), "pre_hire", remark="面试通过"
            )
        except Exception as exc:  # noqa: BLE001 — 流转失败不阻断结论
            _logger.warning(f"面试通过自动流转失败 application={application.id}: {exc}")

    # ── AI 纪要 ──

    async def submit_summary_task(
        self, session: AsyncSession, interview_id: str
    ) -> dict:
        """纪要任务化提交：同面试存在进行中任务时幂等返回既有 task_id。"""
        await self.get_interview(session, interview_id)

        from framework.tasks.enums import TaskStatus
        from iam.models.task import TaskBackground

        active = (
            await session.execute(
                select(TaskBackground.id)
                .where(
                    TaskBackground.task_type == AI_SUMMARY_TASK_TYPE,
                    TaskBackground.resource_id == interview_id,
                    TaskBackground.status.in_(
                        [TaskStatus.PENDING, TaskStatus.PROCESSING]
                    ),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if active:
            return {"task_id": str(active), "duplicated": True}

        from framework.tasks.service import task_service

        task = await task_service.submit(
            session,
            task_type=AI_SUMMARY_TASK_TYPE,
            queue=AI_SUMMARY_QUEUE,
            config_snapshot={
                "interview_id": interview_id,
                "tenant_id": get_tenant_id(),
            },
            resource_type="hr_interview",
            resource_id=interview_id,
        )
        return {"task_id": str(task.id), "duplicated": False}

    async def generate_ai_summary(self, session: AsyncSession, interview_id: str) -> Interview:
        """生成 AI 纪要（基于反馈与简历上下文）；失败抛错可后补重试。"""
        interview = await self.get_interview(session, interview_id)
        row = (
            await session.execute(
                select(CandidateApplication, Candidate, JobRequisition)
                .join(Candidate, CandidateApplication.candidate_id == Candidate.id)
                .join(
                    JobRequisition,
                    CandidateApplication.requisition_id == JobRequisition.id,
                )
                .where(CandidateApplication.id == interview.application_id)
            )
        ).first()
        if row is None:
            raise NotFoundError("面试关联投递不存在")
        application, candidate, requisition = row

        profile = candidate.profile or {}
        resume = str(profile.get("resume_raw") or "")[:2000]
        context = (
            f"候选人：{candidate.name}（应聘「{requisition.title}」第 {interview.round} 轮）\n"
            f"面试形式：{interview.interview_form}\n"
            f"面试反馈：{interview.feedback or '（未填写）'}\n"
            f"简历摘要：{resume or '（无）'}"
        )
        content = await llm_chat(
            self._tenant_id(),
            [
                {
                    "role": "system",
                    "content": "你是 HR 面试纪要助手，输出 200 字以内的中文纪要：候选人亮点、风险点与录用建议。",
                },
                {"role": "user", "content": context},
            ],
        )
        interview.ai_summary = content.strip()
        return interview

    # ── 响应构造 ──

    def to_response(self, interview: Interview) -> InterviewResponse:
        return InterviewResponse(
            id=str(interview.id),
            application_id=str(interview.application_id),
            round=interview.round,
            interviewer_id=str(interview.interviewer_id),
            scheduled_at=interview.scheduled_at,
            interview_form=interview.interview_form,
            result=interview.result,
            feedback=interview.feedback,
            ai_summary=interview.ai_summary,
        )

    @staticmethod
    def _tenant_id() -> str:
        tenant_id = get_tenant_id()
        if not tenant_id:
            raise BadRequestError("缺少租户上下文")
        return tenant_id


interview_service = InterviewService()
