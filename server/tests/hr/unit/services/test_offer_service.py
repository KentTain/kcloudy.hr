"""Offer 服务单元测试

覆盖：创建前置校验（拟录用/一申请一单/有效期）、send-accept-reject 状态机与
申请流转、流转幂等复核、入职转化建档（员工取号回填 + filled_count 联动）。
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ConflictError
from framework.tenant.context import TenantContext

from hr.models import Candidate, CandidateApplication, JobRequisition, Offer
from hr.schemas.recruiting import OfferCreate
from hr.services.offer_service import offer_service


class _FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one(self):
        if self._scalar is not None:
            return self._scalar
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


def _mock_session(get_map=None, execute_results=None) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.flush = AsyncMock()
    added: list = []
    session.add = MagicMock(side_effect=added.append)
    session._added = added

    async def _get(model, pk):
        return (get_map or {}).get((model.__name__, str(pk)))

    session.get = AsyncMock(side_effect=_get)
    session.execute = AsyncMock(
        side_effect=list(execute_results) if execute_results else []
    )
    return session


def _application(**overrides) -> CandidateApplication:
    defaults = dict(
        id="app-1",
        tenant_id="t-1",
        candidate_id="cand-1",
        requisition_id="req-1",
        stage="pre_hire",
        stage_history=[],
        apply_time=datetime.now(UTC),
    )
    defaults.update(overrides)
    return CandidateApplication(**defaults)


def _candidate() -> Candidate:
    return Candidate(
        id="cand-1",
        tenant_id="t-1",
        name="张三",
        phone="13800001111",
        email="zhang@example.com",
        source_channel="zhilian",
    )


def _requisition() -> JobRequisition:
    return JobRequisition(
        id="req-1",
        tenant_id="t-1",
        req_no="REQ001",
        title="Python 工程师",
        org_id="org-1",
        headcount=2,
        job_level="P5",
        priority="medium",
        status="recruiting",
        filled_count=0,
    )


def _offer(**overrides) -> Offer:
    defaults = dict(
        id="offer-1",
        tenant_id="t-1",
        application_id="app-1",
        salary_snapshot={"base": 20000},
        status="pending",
    )
    defaults.update(overrides)
    return Offer(**defaults)


@pytest.fixture(autouse=True)
def _tenant_context():
    TenantContext.set_tenant_id("t-1")
    yield
    TenantContext.clear()


class TestCreateOffer:
    """创建 Offer 单"""

    @pytest.mark.asyncio
    async def test_requires_pre_hire(self):
        session = _mock_session(
            get_map={
                ("CandidateApplication", "app-1"): _application(stage="interviewing")
            }
        )
        data = OfferCreate(
            application_id="app-1", salary_snapshot={"base": 20000}
        )
        with pytest.raises(BadRequestError, match="拟录用"):
            await offer_service.create_offer(session, data)

    @pytest.mark.asyncio
    async def test_duplicate_application_conflict(self):
        session = _mock_session(
            get_map={("CandidateApplication", "app-1"): _application()},
            execute_results=[_FakeResult(rows=[_offer()])],
        )
        data = OfferCreate(
            application_id="app-1", salary_snapshot={"base": 20000}
        )
        with pytest.raises(ConflictError, match="已存在"):
            await offer_service.create_offer(session, data)

    @pytest.mark.asyncio
    async def test_valid_until_must_be_future(self):
        session = _mock_session(
            get_map={("CandidateApplication", "app-1"): _application()},
            execute_results=[_FakeResult(rows=[])],
        )
        data = OfferCreate(
            application_id="app-1",
            salary_snapshot={"base": 20000},
            valid_until=datetime.now(UTC) - timedelta(hours=1),
        )
        with pytest.raises(BadRequestError, match="有效期"):
            await offer_service.create_offer(session, data)

    @pytest.mark.asyncio
    async def test_success(self):
        session = _mock_session(
            get_map={("CandidateApplication", "app-1"): _application()},
            execute_results=[_FakeResult(rows=[])],
        )
        data = OfferCreate(
            application_id="app-1",
            salary_snapshot={"base": 20000, "bonus": 2},
        )
        offer = await offer_service.create_offer(session, data)
        # status="pending" 由列 default 在 INSERT 时应用（单测 mock flush 不触发）
        assert offer.salary_snapshot == {"base": 20000, "bonus": 2}
        assert any(o is offer for o in session._added)


class TestOfferStateMachine:
    """send → accept / reject 状态机"""

    @pytest.mark.asyncio
    async def test_send_transitions_to_offered(self):
        session = _mock_session(
            get_map={("Offer", "offer-1"): _offer(status="pending")}
        )
        with patch(
            "hr.services.offer_service.candidate_service.change_stage",
            new=AsyncMock(),
        ) as change_stage:
            offer = await offer_service.send_offer(session, "offer-1")
        assert offer.status == "sent"
        assert offer.sent_at is not None
        assert change_stage.await_args.args[2] == "offered"

    @pytest.mark.asyncio
    async def test_send_only_from_pending(self):
        session = _mock_session(
            get_map={("Offer", "offer-1"): _offer(status="sent")}
        )
        with pytest.raises(ConflictError, match="不可发送"):
            await offer_service.send_offer(session, "offer-1")

    @pytest.mark.asyncio
    async def test_accept_transitions_to_pre_onboard(self):
        session = _mock_session(
            get_map={("Offer", "offer-1"): _offer(status="sent")}
        )
        with patch(
            "hr.services.offer_service.candidate_service.change_stage",
            new=AsyncMock(),
        ) as change_stage:
            offer = await offer_service.accept_offer(session, "offer-1")
        assert offer.status == "accepted"
        assert change_stage.await_args.args[2] == "pre_onboard"

    @pytest.mark.asyncio
    async def test_accept_expired_conflict(self):
        session = _mock_session(
            get_map={
                ("Offer", "offer-1"): _offer(
                    status="sent",
                    valid_until=datetime.now(UTC) - timedelta(hours=1),
                )
            }
        )
        with pytest.raises(ConflictError, match="有效期"):
            await offer_service.accept_offer(session, "offer-1")

    @pytest.mark.asyncio
    async def test_reject_transitions_to_rejected(self):
        session = _mock_session(
            get_map={("Offer", "offer-1"): _offer(status="sent")}
        )
        with patch(
            "hr.services.offer_service.candidate_service.change_stage",
            new=AsyncMock(),
        ) as change_stage:
            offer = await offer_service.reject_offer(session, "offer-1")
        assert offer.status == "rejected"
        assert change_stage.await_args.args[2] == "rejected"
        assert change_stage.await_args.kwargs["remark"] == "Offer 被拒绝"

    @pytest.mark.asyncio
    async def test_transition_idempotent_when_already_at_target(self):
        """流转撞冲突但申请已在目标阶段 → 幂等命中不抛错"""
        session = _mock_session(
            get_map={
                ("Offer", "offer-1"): _offer(status="pending"),
                ("CandidateApplication", "app-1"): _application(stage="offered"),
            }
        )
        with patch(
            "hr.services.offer_service.candidate_service.change_stage",
            new=AsyncMock(side_effect=ConflictError("阶段流转非法")),
        ):
            offer = await offer_service.send_offer(session, "offer-1")
        assert offer.status == "sent"

    @pytest.mark.asyncio
    async def test_transition_reraises_when_not_at_target(self):
        """流转撞冲突且申请不在目标阶段 → 原样抛出"""
        session = _mock_session(
            get_map={
                ("Offer", "offer-1"): _offer(status="pending"),
                ("CandidateApplication", "app-1"): _application(stage="pre_hire"),
            }
        )
        with patch(
            "hr.services.offer_service.candidate_service.change_stage",
            new=AsyncMock(side_effect=ConflictError("阶段流转非法")),
        ):
            with pytest.raises(ConflictError):
                await offer_service.send_offer(session, "offer-1")


class TestOnboard:
    """入职转化建档"""

    @pytest.mark.asyncio
    async def test_requires_accepted_offer(self):
        session = _mock_session(
            get_map={("Offer", "offer-1"): _offer(status="sent")}
        )
        with pytest.raises(ConflictError, match="已接受"):
            await offer_service.onboard(session, "offer-1")

    @pytest.mark.asyncio
    async def test_requires_pre_onboard_stage(self):
        session = _mock_session(
            get_map={("Offer", "offer-1"): _offer(status="accepted")},
            execute_results=[
                _FakeResult(rows=[(_application(stage="offered"), _candidate(), _requisition())])
            ],
        )
        with pytest.raises(ConflictError, match="待入职"):
            await offer_service.onboard(session, "offer-1")

    @pytest.mark.asyncio
    async def test_success_creates_employee_and_links(self):
        session = _mock_session(
            get_map={("Offer", "offer-1"): _offer(status="accepted")},
            execute_results=[
                _FakeResult(
                    rows=[(_application(stage="pre_onboard"), _candidate(), _requisition())]
                )
            ],
        )
        employee = MagicMock()
        employee.id = "emp-1"
        employee.employee_no = "EMP0001"
        with (
            patch(
                "hr.services.offer_service.employee_service.create_employee",
                new=AsyncMock(return_value=employee),
            ) as create_employee,
            patch(
                "hr.services.offer_service.candidate_service.change_stage",
                new=AsyncMock(),
            ) as change_stage,
        ):
            result = await offer_service.onboard(
                session, "offer-1", hire_date=date(2026, 11, 1)
            )
        assert result == {"employee_id": "emp-1", "employee_no": "EMP0001"}
        created = create_employee.await_args.args[1]
        assert created.name == "张三"
        assert created.org_id == "org-1"
        assert created.status == "probation"
        assert change_stage.await_args.args[2] == "onboarded"
        assert change_stage.await_args.kwargs["employee_id"] == "emp-1"


# --------------------------------------------------------------------- 申请维度查询


class TestGetOfferByApplication:
    """申请维度查 Offer（卡片操作入口）"""

    @pytest.mark.asyncio
    async def test_returns_offer_when_exists(self):
        offer = _offer()
        session = _mock_session(execute_results=[_FakeResult(rows=[offer])])
        assert await offer_service.get_offer_by_application(session, "app-1") is offer

    @pytest.mark.asyncio
    async def test_returns_none_when_not_created(self):
        session = _mock_session(execute_results=[_FakeResult(rows=[])])
        assert await offer_service.get_offer_by_application(session, "app-1") is None
