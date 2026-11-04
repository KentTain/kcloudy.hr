"""招聘需求服务：分步创建 / 检索 / 详情 / 渠道发布与下线 / 三段漏斗统计"""

from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from framework.clients.iam_client import get_iam_client
from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError
from framework.tasks.service import task_service

from hr.models import CandidateApplication, JobPosting, JobRequisition
from hr.schemas.recruiting import (
    FunnelResponse,
    FunnelStat,
    PostingResponse,
    RequisitionCreate,
    RequisitionResponse,
    RequisitionUpdate,
)

_logger = logger.bind(name=__name__)

# 可发布渠道（internal 为站内直投免凭证渠道，恒可发布）
INTERNAL_CHANNEL = "internal"
PUBLISHABLE_CHANNELS = (INTERNAL_CHANNEL, "zhilian", "job51", "liepin")

# 需求状态
REQ_STATUS_DRAFT = "draft"
REQ_STATUS_RECRUITING = "recruiting"
REQ_STATUS_PARTIAL = "partial"
REQ_STATUS_FILLED = "filled"
REQ_STATUS_CLOSED = "closed"

# 发布任务
PUBLISH_TASK_TYPE = "hr_posting_publish"
PUBLISH_QUEUE = "hr-recruiting"


def _refresh_requisition_status(requisition: JobRequisition) -> None:
    """按 filled_count 推进需求状态（filled 达标自动闭环，不覆盖 closed）。"""
    if requisition.status == REQ_STATUS_CLOSED:
        return
    if requisition.filled_count >= requisition.headcount:
        requisition.status = REQ_STATUS_FILLED
    elif requisition.filled_count > 0:
        requisition.status = REQ_STATUS_PARTIAL


class RequisitionService:
    """招聘需求业务"""

    # ── 检索 ──

    async def list_requisitions(
        self,
        session: AsyncSession,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        priority: str | None = None,
        org_id: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[JobRequisition], int]:
        """需求分页筛选（keyword 命中编号/职位名称）。"""
        conditions = []
        if status:
            conditions.append(JobRequisition.status == status)
        if priority:
            conditions.append(JobRequisition.priority == priority)
        if org_id:
            conditions.append(JobRequisition.org_id == org_id)
        if keyword:
            like = f"%{keyword}%"
            conditions.append(
                or_(
                    JobRequisition.req_no.ilike(like),
                    JobRequisition.title.ilike(like),
                )
            )

        total = (
            await session.execute(
                select(func.count(JobRequisition.id)).where(*conditions)
            )
        ).scalar_one()
        result = await session.execute(
            select(JobRequisition)
            .options(selectinload(JobRequisition.postings))
            .where(*conditions)
            .order_by(JobRequisition.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def get_requisition(
        self, session: AsyncSession, requisition_id: str
    ) -> JobRequisition:
        result = await session.execute(
            select(JobRequisition)
            .options(selectinload(JobRequisition.postings))
            .where(JobRequisition.id == requisition_id)
        )
        requisition = result.scalar_one_or_none()
        if not requisition:
            raise NotFoundError(f"招聘需求 {requisition_id} 不存在")
        return requisition

    # ── 生命周期 ──

    async def create_requisition(
        self, session: AsyncSession, data: RequisitionCreate
    ) -> JobRequisition:
        """创建需求（编号自动取号）；channels 非空时创建后立即发布。"""
        if data.headcount <= 0:
            raise BadRequestError("招聘人数须大于 0")
        if (
            data.salary_min is not None
            and data.salary_max is not None
            and data.salary_min > data.salary_max
        ):
            raise BadRequestError("薪酬区间下限不可高于上限")

        tenant_id = self._tenant_id()
        req_no = await get_iam_client().generate_code(session, tenant_id, "requisition_code")
        requisition = JobRequisition(
            tenant_id=tenant_id,
            req_no=req_no,
            title=data.title,
            org_id=data.org_id,
            position_id=data.position_id,
            headcount=data.headcount,
            job_level=data.job_level,
            salary_min=data.salary_min,
            salary_max=data.salary_max,
            priority=data.priority,
            status=REQ_STATUS_DRAFT,
            jd=data.jd,
        )
        session.add(requisition)
        await session.flush()

        if data.channels:
            await self.publish_to_channels(session, str(requisition.id), data.channels)
        return requisition

    async def update_requisition(
        self, session: AsyncSession, requisition_id: str, data: RequisitionUpdate
    ) -> JobRequisition:
        requisition = await self.get_requisition(session, requisition_id)
        if requisition.status == REQ_STATUS_CLOSED:
            raise ConflictError("需求已关闭，不可编辑")
        updates = data.model_dump(exclude_unset=True, exclude_none=True)
        for field, value in updates.items():
            setattr(requisition, field, value)
        return requisition

    async def close_requisition(self, session: AsyncSession, requisition_id: str) -> JobRequisition:
        """人工关闭需求：关闭后拒绝投递与流转。"""
        requisition = await self.get_requisition(session, requisition_id)
        requisition.status = REQ_STATUS_CLOSED
        return requisition

    def ensure_requisition_open(self, requisition: JobRequisition) -> None:
        """投递与流转入口的状态校验（关闭/满编拒绝）。"""
        if requisition.status == REQ_STATUS_CLOSED:
            raise ConflictError("需求已关闭，不再接受投递与流转")
        if requisition.status == REQ_STATUS_FILLED:
            raise ConflictError("需求已满编，不再接受投递与流转")

    # ── 渠道发布 ──

    async def publish_to_channels(
        self, session: AsyncSession, requisition_id: str, channels: list[str]
    ) -> list[JobPosting]:
        """发布需求到渠道：internal 恒可；外部渠道建 publishing 行 + 任务化发布
        （任务回写 external_post_id）；已发布渠道去重跳过。"""
        if not channels:
            raise BadRequestError("须至少选择一个发布渠道")
        unknown = [c for c in channels if c not in PUBLISHABLE_CHANNELS]
        if unknown:
            raise BadRequestError(f"不支持的发布渠道: {', '.join(unknown)}")

        requisition = await self.get_requisition(session, requisition_id)
        self.ensure_requisition_open(requisition)

        tenant_id = self._tenant_id()
        existing = {p.channel for p in requisition.postings if p.status != "offline"}
        postings: list[JobPosting] = []
        for channel in channels:
            if channel in existing:
                continue
            posting = JobPosting(
                tenant_id=tenant_id,
                requisition_id=requisition.id,
                channel=channel,
                status="publishing" if channel != INTERNAL_CHANNEL else "published",
                published_at=datetime.now(UTC) if channel == INTERNAL_CHANNEL else None,
            )
            session.add(posting)
            postings.append(posting)
        await session.flush()

        if requisition.status == REQ_STATUS_DRAFT:
            requisition.status = REQ_STATUS_RECRUITING

        for posting in postings:
            if posting.channel != INTERNAL_CHANNEL:
                await task_service.submit(
                    session,
                    task_type=PUBLISH_TASK_TYPE,
                    queue=PUBLISH_QUEUE,
                    config_snapshot={
                        "tenant_id": tenant_id,
                        "posting_id": str(posting.id),
                    },
                    resource_type="job_posting",
                    resource_id=str(posting.id),
                )
        return postings

    async def offline_posting(self, session: AsyncSession, posting_id: str) -> JobPosting:
        """下线已发布职位：本地置 offline；外部渠道侧同步由任务补偿。"""
        result = await session.execute(
            select(JobPosting).where(JobPosting.id == posting_id)
        )
        posting = result.scalar_one_or_none()
        if not posting:
            raise NotFoundError(f"职位发布记录 {posting_id} 不存在")
        if posting.status == "offline":
            raise ConflictError("该职位已下线")
        posting.status = "offline"
        return posting

    # ── 漏斗统计 ──

    async def get_funnel(
        self, session: AsyncSession, requisition_id: str | None = None
    ) -> FunnelResponse:
        """三段漏斗统计（requisition_id 为空即全局口径，按投递申请计数）。"""
        conditions = []
        if requisition_id:
            conditions.append(CandidateApplication.requisition_id == requisition_id)
        result = await session.execute(
            select(CandidateApplication.stage, func.count())
            .where(*conditions)
            .group_by(CandidateApplication.stage)
        )
        counts = {stage: count for stage, count in result.all()}
        stats = [FunnelStat(stage=stage, count=counts.get(stage, 0)) for stage in self._stage_order()]
        return FunnelResponse(requisition_id=requisition_id, stats=stats)

    @staticmethod
    def _stage_order() -> list[str]:
        return [
            "pending_screening",
            "screening_passed",
            "interviewing",
            "pre_hire",
            "offered",
            "pre_onboard",
            "onboarded",
            "onboard_abandoned",
            "rejected",
            "withdrawn",
        ]

    # ── 响应构造 ──

    def to_response(self, requisition: JobRequisition) -> RequisitionResponse:
        return RequisitionResponse(
            id=str(requisition.id),
            req_no=requisition.req_no,
            title=requisition.title,
            org_id=requisition.org_id,
            position_id=requisition.position_id,
            headcount=requisition.headcount,
            job_level=requisition.job_level,
            salary_min=float(requisition.salary_min) if requisition.salary_min is not None else None,
            salary_max=float(requisition.salary_max) if requisition.salary_max is not None else None,
            priority=requisition.priority,
            status=requisition.status,
            jd=requisition.jd,
            filled_count=requisition.filled_count,
            postings=[
                PostingResponse(
                    id=str(p.id),
                    channel=p.channel,
                    status=p.status,
                    external_post_id=p.external_post_id,
                    published_at=p.published_at,
                )
                for p in sorted(
                    getattr(requisition, "postings", []) or [],
                    key=lambda p: p.channel,
                )
            ],
        )

    @staticmethod
    def _tenant_id() -> str:
        from framework.tenant.context import TenantContext

        tenant_id = TenantContext.get_tenant_id()
        if not tenant_id:
            raise BadRequestError("缺少租户上下文")
        return tenant_id


requisition_service = RequisitionService()
