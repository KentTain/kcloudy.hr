"""候选人服务：手工录入 / 渠道归集幂等入库 / 去重合并 / AI 简历解析 / 漏斗状态机"""

from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.ctx import get_user_id
from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError
from framework.tasks.service import task_service

from hr.models import (
    Candidate,
    CandidateApplication,
    Interview,
    JobRequisition,
)
from hr.services.requisition_service import (
    _refresh_requisition_status,
    requisition_service,
)

_logger = logger.bind(name=__name__)

# 简历解析任务
RESUME_PARSE_TASK_TYPE = "hr_resume_parse"
RESUME_PARSE_QUEUE = "hr-recruiting"

# 漏斗状态机：stage → 允许跃迁的目标阶段集
# 初筛段 pending_screening/screening_passed；面试段 interviewing；
# 录用段 pre_hire/offered/pre_onboard；结果段 onboarded/onboard_abandoned/rejected/withdrawn
_STAGE_TRANSITIONS: dict[str, set[str]] = {
    "pending_screening": {"screening_passed", "rejected", "withdrawn"},
    "screening_passed": {"interviewing", "rejected", "withdrawn"},
    "interviewing": {"pre_hire", "rejected", "withdrawn"},
    "pre_hire": {"offered", "rejected"},
    "offered": {"pre_onboard", "rejected"},
    "pre_onboard": {"onboarded", "onboard_abandoned"},
    # 终态
    "onboarded": set(),
    "onboard_abandoned": set(),
    "rejected": set(),
    "withdrawn": set(),
}

_TERMINAL_STAGES = frozenset(
    {"onboarded", "onboard_abandoned", "rejected", "withdrawn"}
)


def _now() -> datetime:
    return datetime.now(UTC)


class CandidateService:
    """候选人业务"""

    # ── 检索 ──

    async def list_applications(
        self,
        session: AsyncSession,
        *,
        page: int,
        page_size: int,
        stage: str | None = None,
        channel: str | None = None,
        requisition_id: str | None = None,
        keyword: str | None = None,
        include_blacklist: bool = False,
    ) -> tuple[list[tuple[CandidateApplication, Candidate, JobRequisition]], int]:
        """投递卡片流分页（application × candidate × requisition 三联）。

        黑名单默认不展示（include_blacklist 显式开启）。
        """
        conditions = []
        if stage:
            conditions.append(CandidateApplication.stage == stage)
        if channel:
            conditions.append(Candidate.source_channel == channel)
        if requisition_id:
            conditions.append(CandidateApplication.requisition_id == requisition_id)
        if not include_blacklist:
            conditions.append(Candidate.is_blacklist.is_(False))
        if keyword:
            like = f"%{keyword}%"
            conditions.append(
                or_(
                    Candidate.name.ilike(like),
                    Candidate.phone.ilike(like),
                    Candidate.email.ilike(like),
                )
            )

        base = (
            select(CandidateApplication, Candidate, JobRequisition)
            .join(Candidate, CandidateApplication.candidate_id == Candidate.id)
            .join(JobRequisition, CandidateApplication.requisition_id == JobRequisition.id)
            .where(*conditions)
        )
        total = (
            await session.execute(
                select(func.count(CandidateApplication.id))
                .join(Candidate, CandidateApplication.candidate_id == Candidate.id)
                .join(
                    JobRequisition,
                    CandidateApplication.requisition_id == JobRequisition.id,
                )
                .where(*conditions)
            )
        ).scalar_one()
        result = await session.execute(
            base.order_by(CandidateApplication.apply_time.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return [(row[0], row[1], row[2]) for row in result.all()], total

    async def get_application(
        self, session: AsyncSession, application_id: str
    ) -> CandidateApplication:
        application = await session.get(CandidateApplication, application_id)
        if not application:
            raise NotFoundError(f"投递申请 {application_id} 不存在")
        return application

    async def get_candidate(self, session: AsyncSession, candidate_id: str) -> Candidate:
        candidate = await session.get(Candidate, candidate_id)
        if not candidate:
            raise NotFoundError(f"候选人 {candidate_id} 不存在")
        return candidate

    async def merge_suggestions(
        self, session: AsyncSession, candidate_id: str, *, limit: int = 10
    ) -> list[dict]:
        """疑似重复档：手机/邮箱命中其它候选人（合并弹窗建议区直选）。"""
        candidate = await self.get_candidate(session, candidate_id)
        conditions = []
        if candidate.phone:
            conditions.append(Candidate.phone == candidate.phone)
        if candidate.email:
            conditions.append(Candidate.email == candidate.email)
        if not conditions:
            return []
        result = await session.execute(
            select(Candidate)
            .where(
                Candidate.tenant_id == self._tenant_id(),
                Candidate.id != candidate.id,
                or_(*conditions),
            )
            .order_by(Candidate.created_at)
            .limit(limit)
        )
        return [
            {
                "candidate_id": str(row.id),
                "name": row.name,
                "phone": row.phone,
                "email": row.email,
                "matched_by": (
                    "phone" if row.phone and row.phone == candidate.phone else "email"
                ),
            }
            for row in result.scalars().all()
        ]

    # ── 手工录入 ──

    async def create_candidate(
        self,
        session: AsyncSession,
        *,
        name: str,
        phone: str | None = None,
        email: str | None = None,
        source_channel: str = "manual",
        requisition_id: str | None = None,
    ) -> tuple[Candidate, CandidateApplication | None]:
        """手工录入候选人；关联需求时同步产生投递（待初筛）。"""
        if not phone and not email:
            raise BadRequestError("手机号与邮箱至少提供一项")
        tenant_id = self._tenant_id()
        candidate = Candidate(
            tenant_id=tenant_id,
            name=name,
            phone=phone,
            email=email,
            source_channel=source_channel,
        )
        session.add(candidate)
        await session.flush()

        application = None
        if requisition_id:
            application = await self._create_application(
                session,
                tenant_id=tenant_id,
                candidate_id=str(candidate.id),
                requisition_id=requisition_id,
            )
        return candidate, application

    # ── 编辑 / 删除 / 黑名单 ──

    async def update_candidate(
        self, session: AsyncSession, candidate_id: str, updates: dict
    ) -> Candidate:
        candidate = await self.get_candidate(session, candidate_id)
        for field, value in updates.items():
            setattr(candidate, field, value)
        return candidate

    async def delete_candidate(self, session: AsyncSession, candidate_id: str) -> None:
        """删除候选人（级联删除投递申请；在面投递拒绝删除须先淘汰）。"""
        candidate = await self.get_candidate(session, candidate_id)
        result = await session.execute(
            select(CandidateApplication.stage).where(
                CandidateApplication.candidate_id == candidate_id,
                CandidateApplication.stage.in_(["pending_screening", "screening_passed", "interviewing"]),
            )
        )
        if result.first():
            raise ConflictError("候选人存在进行中的投递，须先完成流转或淘汰")
        await session.delete(candidate)

    async def set_blacklist(
        self, session: AsyncSession, candidate_id: str, is_blacklist: bool
    ) -> Candidate:
        candidate = await self.get_candidate(session, candidate_id)
        candidate.is_blacklist = is_blacklist
        return candidate

    # ── 合并 ──

    async def merge_candidates(
        self, session: AsyncSession, source_id: str, target_id: str
    ) -> int:
        """重复档合并：source 的投递与面试记录归并到 target，source 删除。

        返回归并的投递数（需 hr:candidate:merge 权限，控制器侧校验）。
        """
        if source_id == target_id:
            raise BadRequestError("不可与自身合并")
        source = await self.get_candidate(session, source_id)
        await self.get_candidate(session, target_id)

        result = await session.execute(
            select(CandidateApplication).where(
                CandidateApplication.candidate_id == source_id
            )
        )
        applications = list(result.scalars().all())
        for application in applications:
            application.candidate_id = target_id
        await session.flush()
        # 面试经 application 外键级联归属，无需单独迁移
        await session.delete(source)
        return len(applications)

    # ── 渠道归集（幂等 upsert）──

    async def collect_application(
        self,
        session: AsyncSession,
        *,
        channel: str,
        external_candidate_id: str,
        external_application_id: str | None,
        requisition_id: str,
        name: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        resume_url: str | None = None,
        resume_text: str | None = None,
        apply_time: datetime | None = None,
    ) -> tuple[CandidateApplication, dict | None, bool]:
        """渠道归集入库（幂等）：返回 (投递, 合并建议, 是否新建投递)。

        - 候选人档：(tenant, channel, external_candidate_id) 命中复用；
        - 投递：同候选人同需求已有投递则复用（重复 webhook/拉取不重投）；
        - 手机/邮箱命中既有其他候选人 → 返回合并建议（不自动合并）。
        """
        tenant_id = self._tenant_id()

        candidate = await self._find_by_external_id(
            session, tenant_id, channel, external_candidate_id
        )
        suggestion: dict | None = None
        if candidate is None:
            candidate = await self._upsert_new_candidate(
                session,
                tenant_id=tenant_id,
                channel=channel,
                external_candidate_id=external_candidate_id,
                name=name or f"候选人_{external_candidate_id[:8]}",
                phone=phone,
                email=email,
                resume_url=resume_url,
                resume_text=resume_text,
            )
            suggestion = await self._build_merge_suggestion(
                session, tenant_id, candidate
            )

        result = await session.execute(
            select(CandidateApplication).where(
                CandidateApplication.candidate_id == candidate.id,
                CandidateApplication.requisition_id == requisition_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing, suggestion, False

        application = await self._create_application(
            session,
            tenant_id=tenant_id,
            candidate_id=str(candidate.id),
            requisition_id=requisition_id,
            apply_time=apply_time,
        )
        return application, suggestion, True

    async def _find_by_external_id(
        self,
        session: AsyncSession,
        tenant_id: str,
        channel: str,
        external_candidate_id: str,
    ) -> Candidate | None:
        result = await session.execute(
            select(Candidate).where(
                Candidate.tenant_id == tenant_id,
                Candidate.source_channel == channel,
                Candidate.external_candidate_id == external_candidate_id,
            )
        )
        return result.scalar_one_or_none()

    async def _upsert_new_candidate(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        channel: str,
        external_candidate_id: str,
        name: str,
        phone: str | None,
        email: str | None,
        resume_url: str | None,
        resume_text: str | None,
    ) -> Candidate:
        candidate = Candidate(
            tenant_id=tenant_id,
            name=name,
            phone=phone,
            email=email,
            source_channel=channel,
            external_candidate_id=external_candidate_id,
            resume_file=resume_url,
        )
        if resume_text:
            # 原始简历先行留存（profile 待 AI 归一回写；解析失败不阻断归集）
            candidate.profile = {"resume_raw": resume_text, "profile_completed": False}
        session.add(candidate)
        await session.flush()
        return candidate

    async def _build_merge_suggestion(
        self, session: AsyncSession, tenant_id: str, candidate: Candidate
    ) -> dict | None:
        """手机/邮箱命中既有其他候选人 → 合并建议。"""
        conditions = []
        if candidate.phone:
            conditions.append(Candidate.phone == candidate.phone)
        if candidate.email:
            conditions.append(Candidate.email == candidate.email)
        if not conditions:
            return None
        result = await session.execute(
            select(Candidate)
            .where(
                Candidate.tenant_id == tenant_id,
                Candidate.id != candidate.id,
                or_(*conditions),
            )
            .limit(1)
        )
        existing = result.scalar_one_or_none()
        if not existing:
            return None
        return {
            "candidate_id": str(candidate.id),
            "target_id": str(existing.id),
            "matched_by": "phone" if candidate.phone == existing.phone else "email",
        }

    # ── AI 简历解析 ──

    async def trigger_resume_parse(self, session: AsyncSession, candidate_id: str) -> str:
        """触发 AI 简历解析任务（LLM 结构化抽取回写 profile；失败可重试）。"""
        candidate = await self.get_candidate(session, candidate_id)
        tenant_id = self._tenant_id()
        await task_service.submit(
            session,
            task_type=RESUME_PARSE_TASK_TYPE,
            queue=RESUME_PARSE_QUEUE,
            config_snapshot={"tenant_id": tenant_id, "candidate_id": str(candidate.id)},
            resource_type="candidate",
            resource_id=str(candidate.id),
        )
        return str(candidate.id)

    async def apply_resume_profile(
        self, session: AsyncSession, candidate_id: str, profile: dict
    ) -> None:
        """任务消费者回写：AI 归一 profile（保留原始简历留存键）。"""
        candidate = await self.get_candidate(session, candidate_id)
        merged = dict(candidate.profile or {})
        raw = merged.pop("resume_raw", None)
        candidate.profile = {**profile, "profile_completed": True, **({"resume_raw": raw} if raw else {})}

    # ── 漏斗状态机 ──

    async def change_stage(
        self,
        session: AsyncSession,
        application_id: str,
        target_stage: str,
        *,
        remark: str | None = None,
        employee_id: str | None = None,
    ) -> CandidateApplication:
        """阶段流转：状态机校验 + stage_history 追加 + 入职闭环联动。

        onboarded 时 employee_id 回填 + 需求 filled_count +1（状态自动推进
        partial/filled）；offer 域 send/accept 经本方法流转 offered/pre_onboard。
        """
        application = await self.get_application(session, application_id)
        current = application.stage
        if current in _TERMINAL_STAGES:
            raise ConflictError(f"投递已处于终态 {current}，不可再流转")
        allowed = _STAGE_TRANSITIONS.get(current, set())
        if target_stage not in allowed:
            raise ConflictError(f"阶段 {current} 不允许流转到 {target_stage}")

        requisition = await session.get(JobRequisition, application.requisition_id)
        if requisition is not None and target_stage not in ("onboarded",):
            requisition_service.ensure_requisition_open(requisition)

        application.stage = target_stage
        history = list(application.stage_history or [])
        history.append(
            {
                "stage": target_stage,
                "operator_id": get_user_id(),
                "operated_at": _now().isoformat(),
                "remark": remark,
            }
        )
        application.stage_history = history

        if target_stage == "onboarded":
            if employee_id:
                application.employee_id = employee_id
            if requisition is not None:
                requisition.filled_count = (requisition.filled_count or 0) + 1
                _refresh_requisition_status(requisition)
        return application

    async def list_candidate_applications(
        self, session: AsyncSession, candidate_id: str
    ) -> list[CandidateApplication]:
        result = await session.execute(
            select(CandidateApplication)
            .where(CandidateApplication.candidate_id == candidate_id)
            .order_by(CandidateApplication.apply_time.desc())
        )
        return list(result.scalars().all())

    async def count_application_interviews(
        self, session: AsyncSession, application_id: str
    ) -> int:
        return (
            await session.execute(
                select(func.count(Interview.id)).where(
                    Interview.application_id == application_id
                )
            )
        ).scalar_one()

    # ------------------------------------------------------------------ 内部

    async def _create_application(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        candidate_id: str,
        requisition_id: str,
        apply_time: datetime | None = None,
    ) -> CandidateApplication:
        requisition = await session.get(JobRequisition, requisition_id)
        if not requisition:
            raise NotFoundError(f"招聘需求 {requisition_id} 不存在")
        requisition_service.ensure_requisition_open(requisition)

        application = CandidateApplication(
            tenant_id=tenant_id,
            candidate_id=candidate_id,
            requisition_id=requisition_id,
            stage="pending_screening",
            stage_history=[
                {
                    "stage": "pending_screening",
                    "operator_id": get_user_id(),
                    "operated_at": _now().isoformat(),
                    "remark": None,
                }
            ],
            apply_time=apply_time or _now(),
        )
        session.add(application)
        await session.flush()
        return application

    @staticmethod
    def _tenant_id() -> str:
        from framework.tenant.context import TenantContext

        tenant_id = TenantContext.get_tenant_id()
        if not tenant_id:
            raise BadRequestError("缺少租户上下文")
        return tenant_id


candidate_service = CandidateService()
