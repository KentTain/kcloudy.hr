"""招聘聚合单服务（流程测试载体）：父=招聘需求、明细=申请（内嵌候选人）、孙=Offer（1:1）

聚合接口请求体即父子孙嵌套结构，供接口库导入与表单向导生成三级表单。
编排复用 requisition/candidate/offer 三服务；行内带 Offer 时先把申请推进
拟录用（pre_hire，带流转史）再发 Offer，保持域规则一致。明细编辑按行
upsert：带 application_id 更新、不带新建、缺失删除（Offer/面试随外键级联，
候选人档保留）。
"""

from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.ctx import get_user_id
from framework.common.exceptions import NotFoundError

from hr.models import Candidate, CandidateApplication, JobRequisition, Offer
from hr.schemas.recruiting import (
    BundleApplicationInput,
    BundleApplicationResponse,
    BundleOfferInput,
    BundleOfferResponse,
    OfferCreate,
    RequisitionBundleCreate,
    RequisitionBundleDetailResponse,
    RequisitionBundleListItem,
    RequisitionBundleUpdate,
    RequisitionCreate,
    RequisitionUpdate,
)
from hr.services.candidate_service import candidate_service
from hr.services.offer_service import offer_service
from hr.services.requisition_service import requisition_service


def _now() -> datetime:
    return datetime.now(UTC)


def _offer_response(offer: Offer) -> BundleOfferResponse:
    snapshot = offer.salary_snapshot or {}
    return BundleOfferResponse(
        offer_id=str(offer.id),
        monthly_salary=float(snapshot.get("monthly_salary") or 0),
        sign_on_bonus=snapshot.get("sign_on_bonus"),
        year_end_bonus=snapshot.get("year_end_bonus"),
        valid_until=offer.valid_until,
        status=offer.status,
    )


class RequisitionBundleService:
    """招聘聚合单业务（流程测试）"""

    # ── 检索 ──

    async def list_bundles(
        self,
        session: AsyncSession,
        *,
        page: int,
        page_size: int,
        keyword: str | None = None,
    ) -> tuple[list[RequisitionBundleListItem], int]:
        """聚合单分页（需求行 + 申请数/Offer 数统计）。"""
        conditions = []
        if keyword:
            like = f"%{keyword}%"
            conditions.append(
                or_(JobRequisition.req_no.ilike(like), JobRequisition.title.ilike(like))
            )
        total = (
            await session.execute(
                select(func.count(JobRequisition.id)).where(*conditions)
            )
        ).scalar_one()
        result = await session.execute(
            select(JobRequisition)
            .where(*conditions)
            .order_by(JobRequisition.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        requisitions = list(result.scalars().all())
        if not requisitions:
            return [], total
        ids = [str(item.id) for item in requisitions]
        app_counts = dict(
            (
                await session.execute(
                    select(
                        CandidateApplication.requisition_id, func.count()
                    )
                    .where(CandidateApplication.requisition_id.in_(ids))
                    .group_by(CandidateApplication.requisition_id)
                )
            ).all()
        )
        offer_counts = dict(
            (
                await session.execute(
                    select(CandidateApplication.requisition_id, func.count())
                    .select_from(Offer)
                    .join(
                        CandidateApplication,
                        Offer.application_id == CandidateApplication.id,
                    )
                    .where(CandidateApplication.requisition_id.in_(ids))
                    .group_by(CandidateApplication.requisition_id)
                )
            ).all()
        )
        items = [
            RequisitionBundleListItem(
                id=str(item.id),
                req_no=item.req_no,
                title=item.title,
                org_id=item.org_id,
                headcount=item.headcount,
                priority=item.priority,
                status=item.status,
                application_count=app_counts.get(str(item.id), 0),
                offer_count=offer_counts.get(str(item.id), 0),
            )
            for item in requisitions
        ]
        return items, total

    async def get_bundle_detail(
        self, session: AsyncSession, requisition_id: str
    ) -> RequisitionBundleDetailResponse:
        """聚合详情：需求字段 + 申请明细行（候选人字段 + 行内 Offer）。"""
        requisition = await requisition_service.get_requisition(session, requisition_id)
        rows = (
            await session.execute(
                select(CandidateApplication, Candidate)
                .join(Candidate, CandidateApplication.candidate_id == Candidate.id)
                .where(CandidateApplication.requisition_id == requisition_id)
                .order_by(CandidateApplication.created_at.asc())
            )
        ).all()
        offers: dict[str, Offer] = {}
        if rows:
            result = await session.execute(
                select(Offer).where(
                    Offer.application_id.in_([str(row.id) for row, _ in rows])
                )
            )
            offers = {str(offer.application_id): offer for offer in result.scalars()}

        applications = [
            BundleApplicationResponse(
                application_id=str(application.id),
                candidate_id=str(candidate.id),
                candidate_name=candidate.name,
                candidate_phone=candidate.phone,
                candidate_email=candidate.email,
                candidate_source_channel=candidate.source_channel,
                stage=application.stage,
                match_score=float(application.match_score)
                if application.match_score is not None
                else None,
                apply_time=application.apply_time,
                offer=_offer_response(offers[str(application.id)])
                if str(application.id) in offers
                else None,
            )
            for application, candidate in rows
        ]
        return RequisitionBundleDetailResponse(
            id=str(requisition.id),
            req_no=requisition.req_no,
            title=requisition.title,
            org_id=requisition.org_id,
            position_id=requisition.position_id,
            headcount=requisition.headcount,
            job_level=requisition.job_level,
            salary_min=requisition.salary_min,
            salary_max=requisition.salary_max,
            priority=requisition.priority,
            status=requisition.status,
            jd=requisition.jd,
            applications=applications,
        )

    # ── 生命周期 ──

    async def create_bundle(
        self, session: AsyncSession, data: RequisitionBundleCreate
    ) -> RequisitionBundleDetailResponse:
        """创建聚合单：需求 + 明细行（候选人+投递）+ 行内 Offer，一次事务落库。"""
        requisition = await requisition_service.create_requisition(
            session,
            RequisitionCreate(
                title=data.title,
                org_id=data.org_id,
                position_id=data.position_id,
                headcount=data.headcount,
                job_level=data.job_level,
                salary_min=data.salary_min,
                salary_max=data.salary_max,
                priority=data.priority,
                jd=data.jd,
            ),
        )
        for row in data.applications:
            await self._upsert_row(session, str(requisition.id), row)
        return await self.get_bundle_detail(session, str(requisition.id))

    async def update_bundle(
        self, session: AsyncSession, requisition_id: str, data: RequisitionBundleUpdate
    ) -> RequisitionBundleDetailResponse:
        """编辑聚合单：父字段更新（关闭守卫复用）+ 明细按行 upsert + 缺失行删除。"""
        await requisition_service.get_requisition(session, requisition_id)
        await requisition_service.update_requisition(
            session,
            requisition_id,
            RequisitionUpdate(**data.model_dump(exclude={"applications"}, exclude_none=True)),
        )
        existing_ids = set(
            (
                await session.execute(
                    select(CandidateApplication.id).where(
                        CandidateApplication.requisition_id == requisition_id
                    )
                )
            ).scalars()
        )
        for row in data.applications:
            await self._upsert_row(session, requisition_id, row)
        kept_ids = {row.application_id for row in data.applications if row.application_id}
        for orphan_id in {str(item) for item in existing_ids} - kept_ids:
            await session.delete(
                await candidate_service.get_application(session, orphan_id)
            )
        return await self.get_bundle_detail(session, requisition_id)

    # ── 内部 ──

    async def _upsert_row(
        self, session: AsyncSession, requisition_id: str, row: BundleApplicationInput
    ) -> None:
        """明细行 upsert：带 id 更新既有行（候选人随行更新），否则新建候选人+投递。"""
        if row.application_id:
            application = await candidate_service.get_application(session, row.application_id)
            if str(application.requisition_id) != requisition_id:
                raise NotFoundError(f"投递申请 {row.application_id} 不属于该需求")
            candidate = await candidate_service.get_candidate(
                session, str(application.candidate_id)
            )
            candidate.name = row.candidate_name
            candidate.phone = row.candidate_phone
            candidate.email = row.candidate_email
            candidate.source_channel = row.candidate_source_channel
        else:
            _, application = await candidate_service.create_candidate(
                session,
                name=row.candidate_name,
                phone=row.candidate_phone,
                email=row.candidate_email,
                source_channel=row.candidate_source_channel,
                requisition_id=requisition_id,
            )
        application.match_score = row.match_score
        if row.offer is not None:
            await self._upsert_offer(session, application, row.offer)
        await session.flush()

    async def _upsert_offer(
        self,
        session: AsyncSession,
        application: CandidateApplication,
        offer_input: BundleOfferInput,
    ) -> None:
        """行内 Offer upsert：新发 Offer 须申请处于拟录用（推进带流转史），既有单更新快照与有效期。"""
        existing = (
            await session.execute(
                select(Offer).where(Offer.application_id == str(application.id))
            )
        ).scalar_one_or_none()
        snapshot = {
            key: value
            for key, value in {
                "monthly_salary": offer_input.monthly_salary,
                "sign_on_bonus": offer_input.sign_on_bonus,
                "year_end_bonus": offer_input.year_end_bonus,
            }.items()
            if value is not None
        }
        if existing is None:
            if application.stage != "pre_hire":
                application.stage = "pre_hire"
                application.stage_history = [
                    *(application.stage_history or []),
                    {
                        "stage": "pre_hire",
                        "operator_id": get_user_id(),
                        "operated_at": _now().isoformat(),
                        "remark": "聚合单维护：随单发放 Offer 推进拟录用",
                    },
                ]
            await offer_service.create_offer(
                session,
                OfferCreate(
                    application_id=str(application.id),
                    salary_snapshot=snapshot,
                    valid_until=offer_input.valid_until,
                ),
            )
        else:
            existing.salary_snapshot = snapshot
            existing.valid_until = offer_input.valid_until


requisition_bundle_service = RequisitionBundleService()
