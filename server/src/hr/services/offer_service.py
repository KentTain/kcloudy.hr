"""Offer 服务：定薪快照 / 有效期 / send-accept-reject 状态机 / 入职转化建档"""

from datetime import UTC, date, datetime

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.ctx import get_tenant_id
from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError

from hr.models import Candidate, CandidateApplication, JobRequisition, Offer
from hr.schemas.employee import EmployeeCreate
from hr.schemas.recruiting import OfferResponse
from hr.services.candidate_service import candidate_service
from hr.services.employee_service import employee_service

_logger = logger.bind(name=__name__)


def _now() -> datetime:
    return datetime.now(UTC)


class OfferService:
    """Offer 业务"""

    # ── 创建 / 查询 ──

    async def create_offer(self, session: AsyncSession, data) -> Offer:
        """创建 Offer 单：申请须「拟录用」（pre_hire）；一申请至多一单。"""
        application = await candidate_service.get_application(
            session, data.application_id
        )
        if application.stage != "pre_hire":
            raise BadRequestError(
                f"投递阶段为 {application.stage}，须先完成面试通过（拟录用）再发 Offer"
            )
        existing = (
            await session.execute(
                select(Offer).where(Offer.application_id == data.application_id)
            )
        ).scalar_one_or_none()
        if existing:
            raise ConflictError("该投递已存在 Offer 单")

        if data.valid_until and data.valid_until <= _now():
            raise BadRequestError("Offer 有效期须晚于当前时间")

        offer = Offer(
            tenant_id=get_tenant_id(),
            application_id=data.application_id,
            salary_snapshot=data.salary_snapshot,
            valid_until=data.valid_until,
        )
        session.add(offer)
        await session.flush()
        return offer

    async def get_offer(self, session: AsyncSession, offer_id: str) -> Offer:
        offer = await session.get(Offer, offer_id)
        if not offer:
            raise NotFoundError(f"Offer {offer_id} 不存在")
        return offer

    async def get_offer_by_application(
        self, session: AsyncSession, application_id: str
    ) -> Offer | None:
        """申请维度查 Offer（一申请至多一单；未发返回 None）"""
        return (
            await session.execute(
                select(Offer).where(Offer.application_id == application_id)
            )
        ).scalar_one_or_none()

    # ── 状态机 ──

    async def send_offer(self, session: AsyncSession, offer_id: str) -> Offer:
        """发送 Offer：pending → sent；申请流转 pre_hire → offered。"""
        offer = await self.get_offer(session, offer_id)
        if offer.status != "pending":
            raise ConflictError(f"Offer 状态为 {offer.status}，不可发送")
        offer.status = "sent"
        offer.sent_at = _now()
        await self._transition_application(session, offer, "offered")
        return offer

    async def accept_offer(self, session: AsyncSession, offer_id: str) -> Offer:
        """候选人接受：sent → accepted；申请流转 offered → pre_onboard。"""
        offer = await self.get_offer(session, offer_id)
        if offer.status != "sent":
            raise ConflictError(f"Offer 状态为 {offer.status}，不可接受")
        if offer.valid_until and offer.valid_until <= _now():
            raise ConflictError("Offer 已过有效期")
        offer.status = "accepted"
        await self._transition_application(session, offer, "pre_onboard")
        return offer

    async def reject_offer(self, session: AsyncSession, offer_id: str) -> Offer:
        """候选人拒绝：sent → rejected；申请流转 offered → rejected（淘汰）。"""
        offer = await self.get_offer(session, offer_id)
        if offer.status != "sent":
            raise ConflictError(f"Offer 状态为 {offer.status}，不可标记拒绝")
        offer.status = "rejected"
        await self._transition_application(session, offer, "rejected", remark="Offer 被拒绝")
        return offer

    # ── 入职转化 ──

    async def onboard(
        self,
        session: AsyncSession,
        offer_id: str,
        *,
        hire_date: date | None = None,
        position_id: str | None = None,
    ) -> dict:
        """入职转化：accepted Offer → 员工建档 → 申请流转 onboarded（filled_count 联动）。

        员工档取候选人主档 + 需求组织/岗位/职级；建档复用员工域
        create_employee（自动取号 + hire 异动流水）。
        """
        offer = await self.get_offer(session, offer_id)
        if offer.status != "accepted":
            raise ConflictError("仅已接受的 Offer 可办理入职转化")

        row = (
            await session.execute(
                select(CandidateApplication, Candidate, JobRequisition)
                .join(Candidate, CandidateApplication.candidate_id == Candidate.id)
                .join(
                    JobRequisition,
                    CandidateApplication.requisition_id == JobRequisition.id,
                )
                .where(CandidateApplication.id == offer.application_id)
            )
        ).first()
        if row is None:
            raise NotFoundError("Offer 关联投递不存在")
        application, candidate, requisition = row
        if application.stage != "pre_onboard":
            raise ConflictError(
                f"投递阶段为 {application.stage}，须先确认 Offer 接受（待入职）"
            )

        employee = await employee_service.create_employee(
            session,
            EmployeeCreate(
                name=candidate.name,
                phone=candidate.phone,
                work_email=candidate.email,
                org_id=requisition.org_id,
                position_id=position_id or requisition.position_id,
                job_level=requisition.job_level,
                status="probation",
                hire_date=hire_date or date.today(),
            ),
        )
        await candidate_service.change_stage(
            session,
            str(application.id),
            "onboarded",
            remark="入职转化建档",
            employee_id=str(employee.id),
        )
        _logger.info(
            f"入职转化完成 offer={offer_id} employee={employee.employee_no}"
        )
        return {"employee_id": str(employee.id), "employee_no": employee.employee_no}

    # ── 响应构造 ──

    def to_response(self, offer: Offer) -> OfferResponse:
        return OfferResponse(
            id=str(offer.id),
            application_id=str(offer.application_id),
            salary_snapshot=offer.salary_snapshot,
            status=offer.status,
            valid_until=offer.valid_until,
            sent_at=offer.sent_at,
        )

    # ------------------------------------------------------------------ 内部

    async def _transition_application(
        self,
        session: AsyncSession,
        offer: Offer,
        target_stage: str,
        *,
        remark: str | None = None,
    ) -> None:
        try:
            await candidate_service.change_stage(
                session, str(offer.application_id), target_stage, remark=remark
            )
        except ConflictError as exc:
            # 目标阶段不一致（重复操作/并发流转）视为幂等命中
            application = await candidate_service.get_application(
                session, str(offer.application_id)
            )
            if application.stage != target_stage:
                raise
            _logger.info(f"申请已处于 {target_stage}，跳过流转: {exc}")


offer_service = OfferService()
