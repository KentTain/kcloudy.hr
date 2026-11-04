"""员工自助服务单元测试

覆盖：user_id 本人定位（未关联 404）、薪酬单仅由已发放批次生成（明细期间
聚合/明细条目）、团队成员仅负责人可见（所负责组织子树，非负责人返回空）、
我的目标
（分组/归属/active 周期门控）、我的绩效（系数仅收口、最终评级校准优先）、
变更申请（委托审批服务、本人作用域）、团队工作台（组织子树/面试官/评估人
归属裁剪与评分双校验）。
"""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from framework.tenant.context import TenantContext

from hr.models import (
    Candidate,
    CandidateApplication,
    Employee,
    Interview,
    JobRequisition,
    PayrollEntry,
    PayrollRun,
    PerfCycle,
    PerfGoal,
    PerfReview,
)
from hr.services.self_service_service import self_service_service


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

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


def _mock_session(execute_results=None) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.execute = AsyncMock(
        side_effect=list(execute_results) if execute_results else []
    )
    return session


def _employee(**overrides) -> Employee:
    defaults = dict(
        id="emp-1", tenant_id="t-1", employee_no="EMP0001",
        name="张三", status="regular", user_id="u-1", org_id="org-1",
        hire_date=date(2024, 1, 1),
    )
    defaults.update(overrides)
    return Employee(**defaults)


def _run(**overrides) -> PayrollRun:
    defaults = dict(
        id="run-1", tenant_id="t-1", period="2026-09",
        status="paid", pay_date=date(2026, 10, 10),
    )
    defaults.update(overrides)
    return PayrollRun(**defaults)


def _entry(**overrides) -> PayrollEntry:
    defaults = dict(
        id="entry-1", tenant_id="t-1", run_id="run-1", employee_id="emp-1",
        item_id="item-1", item_code="base_monthly", amount=Decimal("4700.00"),
    )
    defaults.update(overrides)
    return PayrollEntry(**defaults)


@pytest.fixture(autouse=True)
def _tenant_context():
    TenantContext.set_tenant_id("t-1")
    yield
    TenantContext.clear()


def _locate(employee: Employee):
    return patch(
        "hr.services.employee_service.employee_service.get_employee_by_user_id",
        new=AsyncMock(return_value=employee),
    )


class TestLocateSelf:
    """本人定位"""

    @pytest.mark.asyncio
    async def test_unlinked_user_raises(self):
        session = _mock_session()
        with (
            patch(
                "hr.services.employee_service.employee_service.get_employee_by_user_id",
                new=AsyncMock(side_effect=NotFoundError("无关联员工档案")),
            ),
            pytest.raises(NotFoundError),
        ):
            await self_service_service.get_profile(session, "u-404")


class TestPaySlips:
    """我的薪酬单"""

    @pytest.mark.asyncio
    async def test_list_only_paid_runs(self):
        session = _mock_session(
            execute_results=[
                _FakeResult(
                    rows=[
                        ("run-1", "2026-09", date(2026, 10, 10), 2, Decimal("5000.00"))
                    ]
                )
            ]
        )
        with _locate(_employee()):
            items = await self_service_service.list_pay_slips(session, "u-1")
        assert len(items) == 1
        assert items[0]["period"] == "2026-09"
        assert items[0]["item_count"] == 2
        assert items[0]["total_amount"] == 5000.0

    @pytest.mark.asyncio
    async def test_detail_items(self):
        session = _mock_session(
            execute_results=[
                _FakeResult(rows=[_run()]),
                _FakeResult(
                    rows=[
                        _entry(),
                        _entry(id="entry-2", item_code="base_monthly"),
                    ]
                ),
            ]
        )
        with _locate(_employee()):
            result = await self_service_service.get_pay_slip(session, "u-1", "2026-09")
        assert result["period"] == "2026-09"
        assert result["total_amount"] == 9400.0
        assert [item["item_code"] for item in result["items"]] == [
            "base_monthly",
            "base_monthly",
        ]

    @pytest.mark.asyncio
    async def test_unpaid_period_not_found(self):
        session = _mock_session(execute_results=[_FakeResult(rows=[])])
        with (
            _locate(_employee()),
            pytest.raises(NotFoundError, match="已发放"),
        ):
            await self_service_service.get_pay_slip(session, "u-1", "2026-10")


class TestTeamEmployees:
    """团队成员（经理视角）"""

    @pytest.mark.asyncio
    async def test_non_leader_returns_empty(self):
        """非负责人（即便挂靠组织）→ 空集（is_leader 判定收紧）"""
        session = _mock_session(execute_results=[_FakeResult(rows=[])])
        with _locate(_employee()):
            result = await self_service_service.list_team_employees(session, "u-1")
        assert result == {"total": 0, "items": []}

    @pytest.mark.asyncio
    async def test_scoped_to_led_org_subtree(self):
        """负责人 → 所负责组织子树成员"""
        session = _mock_session(
            execute_results=[
                _FakeResult(rows=[("org-1",)]),
                _FakeResult(scalar=1),
                _FakeResult(rows=[_employee(id="emp-2", user_id="u-2")]),
            ]
        )
        with (
            _locate(_employee()),
            patch(
                "hr.services.employee_service.employee_service.expand_org_ids",
                new=AsyncMock(return_value=["org-1", "org-1-1"]),
            ) as expand,
        ):
            result = await self_service_service.list_team_employees(
                session, "u-1", page=1, page_size=20
            )
        expand.assert_awaited_once_with(session, "org-1")
        assert result["total"] == 1
        assert result["items"][0].employee_no == "EMP0001"


def _cycle(**overrides) -> PerfCycle:
    defaults = dict(
        id="cyc-1", tenant_id="t-1", name="2026-H1",
        start_date=date(2026, 1, 1), end_date=date(2026, 6, 30), status="active",
    )
    defaults.update(overrides)
    return PerfCycle(**defaults)


def _goal(**overrides) -> PerfGoal:
    defaults = dict(
        id="goal-1", tenant_id="t-1", cycle_id="cyc-1", employee_id="emp-1",
        code="G-001", name="交付达成", weight=Decimal("60.00"), progress=80,
    )
    defaults.update(overrides)
    return PerfGoal(**defaults)


def _review(**overrides) -> PerfReview:
    defaults = dict(
        id="rev-1", tenant_id="t-1", cycle_id="cyc-1", employee_id="emp-1",
        reviewer_employee_id="emp-9", status="submitted",
        score=Decimal("86.00"), rating="B",
    )
    defaults.update(overrides)
    return PerfReview(**defaults)


def _requisition(**overrides) -> JobRequisition:
    defaults = dict(
        id="req-1", tenant_id="t-1", req_no="REQ-001", title="后端工程师",
        org_id="org-1", headcount=2, priority="high", status="open", filled_count=0,
    )
    defaults.update(overrides)
    return JobRequisition(**defaults)


def _interview(**overrides) -> Interview:
    defaults = dict(
        id="itv-1", tenant_id="t-1", application_id="app-1", round=1,
        interviewer_id="emp-1", scheduled_at=datetime(2026, 10, 20, 10, 0),
        interview_form="onsite", result="pending",
    )
    defaults.update(overrides)
    return Interview(**defaults)


def _application(**overrides) -> CandidateApplication:
    defaults = dict(
        id="app-1", tenant_id="t-1", candidate_id="cand-1",
        requisition_id="req-1", stage="interviewing",
    )
    defaults.update(overrides)
    return CandidateApplication(**defaults)


def _candidate(**overrides) -> Candidate:
    defaults = dict(id="cand-1", tenant_id="t-1", name="李四", phone="13800000000")
    defaults.update(overrides)
    return Candidate(**defaults)


class TestMyGoals:
    """我的目标"""

    @pytest.mark.asyncio
    async def test_grouped_by_cycle_active_first(self):
        active = _cycle()
        closed = _cycle(id="cyc-0", name="2025-H2", status="closed",
                        start_date=date(2025, 7, 1), end_date=date(2025, 12, 31))
        session = _mock_session(
            execute_results=[_FakeResult(rows=[(_goal(), active), (_goal(id="goal-2", cycle_id="cyc-0", code="G-000", weight=Decimal("40.00"), progress=100), closed)])]
        )
        with _locate(_employee()):
            items = await self_service_service.list_my_goals(session, "u-1")
        assert [g["cycle_status"] for g in items] == ["active", "closed"]
        assert items[0]["goals"][0]["name"] == "交付达成"
        assert items[0]["goals"][0]["weight"] == 60.0
        assert items[1]["goals"][0]["progress"] == 100

    @pytest.mark.asyncio
    async def test_update_progress_success(self):
        goal = _goal()
        session = _mock_session()
        session.get = AsyncMock(side_effect=[goal, _cycle()])
        with _locate(_employee()):
            updated = await self_service_service.update_my_goal_progress(
                session, "u-1", "goal-1", progress=90, actual_value="9/10"
            )
        assert updated.progress == 90
        assert updated.actual_value == "9/10"

    @pytest.mark.asyncio
    async def test_update_other_employees_goal_forbidden(self):
        goal = _goal(employee_id="emp-2")
        session = _mock_session()
        session.get = AsyncMock(return_value=goal)
        with (
            _locate(_employee()),
            pytest.raises(ForbiddenError),
        ):
            await self_service_service.update_my_goal_progress(session, "u-1", "goal-1", progress=50)

    @pytest.mark.asyncio
    async def test_update_progress_non_active_cycle_conflict(self):
        session = _mock_session()
        session.get = AsyncMock(side_effect=[_goal(), _cycle(status="scoring")])
        with (
            _locate(_employee()),
            pytest.raises(ConflictError, match="active"),
        ):
            await self_service_service.update_my_goal_progress(session, "u-1", "goal-1", progress=50)

    @pytest.mark.asyncio
    async def test_update_progress_out_of_range(self):
        session = _mock_session()
        session.get = AsyncMock(side_effect=[_goal(), _cycle()])
        with (
            _locate(_employee()),
            pytest.raises(BadRequestError),
        ):
            await self_service_service.update_my_goal_progress(session, "u-1", "goal-1", progress=150)


class TestMyReviews:
    """我的绩效"""

    @pytest.mark.asyncio
    async def test_coefficient_only_closed_and_calibrated_preferred(self):
        closed = _cycle(status="closed")
        scoring = _cycle(id="cyc-2", name="2026-H2", status="scoring",
                         start_date=date(2026, 7, 1), end_date=date(2026, 12, 31))
        session = _mock_session(
            execute_results=[_FakeResult(rows=[
                (_review(coefficient=Decimal("1.20")), closed),
                (_review(id="rev-2", cycle_id="cyc-2", status="pending"), scoring),
            ])]
        )
        with _locate(_employee()):
            items = await self_service_service.list_my_reviews(session, "u-1")
        assert items[0]["final_rating"] == "B"
        assert items[0]["coefficient"] == 1.2
        assert items[1]["coefficient"] is None

    @pytest.mark.asyncio
    async def test_final_rating_prefers_calibrated(self):
        closed = _cycle(status="closed")
        session = _mock_session(
            execute_results=[_FakeResult(rows=[
                (_review(rating="A", calibrated_rating="B", coefficient=Decimal("1.00")), closed),
            ])]
        )
        with _locate(_employee()):
            items = await self_service_service.list_my_reviews(session, "u-1")
        assert items[0]["final_rating"] == "B"


class TestChangeRequests:
    """档案变更申请（委托统一审批流）"""

    @pytest.mark.asyncio
    async def test_submit_delegates_to_approval_service(self):
        session = _mock_session()
        request = AsyncMock()
        request.id = "ar-1"
        request.status = "pending"
        with (
            _locate(_employee()),
            patch(
                "hr.services.self_service_service.approval_service.submit",
                new=AsyncMock(return_value=request),
            ) as submit,
        ):
            result = await self_service_service.submit_change_request(
                session, "u-1", title="修改联系方式",
                changes=[{"definition_id": "def-1", "new_value": "13900000000"}],
            )
        submit.assert_awaited_once()
        kwargs = submit.await_args.kwargs
        assert kwargs["biz_type"] == "profile_change"
        assert kwargs["applicant_employee_id"] == "emp-1"
        assert kwargs["applicant_user_id"] == "u-1"
        assert kwargs["payload"]["changes"][0]["definition_id"] == "def-1"
        assert result == {"id": "ar-1", "status": "pending"}

    @pytest.mark.asyncio
    async def test_list_scoped_to_applicant(self):
        session = _mock_session()
        with (
            _locate(_employee()),
            patch(
                "hr.services.self_service_service.approval_service.list_requests",
                new=AsyncMock(return_value={"total": 0, "items": []}),
            ) as list_requests,
        ):
            await self_service_service.list_my_change_requests(session, "u-1", page=1, page_size=20)
        kwargs = list_requests.await_args.kwargs
        assert kwargs["biz_type"] == "profile_change"
        assert kwargs["applicant_employee_id"] == "emp-1"

    @pytest.mark.asyncio
    async def test_cancel_passes_operator_employee(self):
        session = _mock_session()
        with (
            _locate(_employee()),
            patch(
                "hr.services.self_service_service.approval_service.cancel",
                new=AsyncMock(),
            ) as cancel,
        ):
            await self_service_service.cancel_change_request(session, "u-1", "ar-1")
        cancel.assert_awaited_once_with(session, "ar-1", operator_employee_id="emp-1")


class TestTeamRequisitions:
    """团队招聘（组织子树）"""

    @pytest.mark.asyncio
    async def test_no_org_returns_empty(self):
        session = _mock_session()
        with _locate(_employee(org_id=None)):
            result = await self_service_service.list_team_requisitions(session, "u-1")
        assert result == {"total": 0, "items": []}

    @pytest.mark.asyncio
    async def test_scoped_to_own_org_subtree(self):
        session = _mock_session(
            execute_results=[_FakeResult(scalar=1), _FakeResult(rows=[_requisition()])]
        )
        with (
            _locate(_employee()),
            patch(
                "hr.services.employee_service.employee_service.expand_org_ids",
                new=AsyncMock(return_value=["org-1", "org-1-1"]),
            ),
        ):
            result = await self_service_service.list_team_requisitions(session, "u-1")
        assert result["total"] == 1
        assert result["items"][0].req_no == "REQ-001"


class TestTeamInterviews:
    """我的面试（面试官归属）"""

    @pytest.mark.asyncio
    async def test_only_own_interviews_with_names(self):
        session = _mock_session(
            execute_results=[
                _FakeResult(rows=[(_interview(), _requisition(), _candidate())])
            ]
        )
        with _locate(_employee()):
            items = await self_service_service.list_team_interviews(session, "u-1")
        assert len(items) == 1
        assert items[0]["candidate_name"] == "李四"
        assert items[0]["requisition_title"] == "后端工程师"
        assert items[0]["result"] == "pending"


class TestTeamReviews:
    """待我评分（评估人归属 + scoring 态 + 待评分）"""

    @pytest.mark.asyncio
    async def test_pending_reviews_with_goal_stats(self):
        review = _review(status="pending")
        cycle = _cycle(status="scoring")
        session = _mock_session(
            execute_results=[
                _FakeResult(rows=[(review, cycle)]),
                _FakeResult(rows=[_employee(id="emp-1", user_id="u-2")]),
                _FakeResult(rows=[("cyc-1", "emp-1", 2, Decimal("8000"))]),
            ]
        )
        with _locate(_employee()):
            items = await self_service_service.list_team_reviews(session, "u-1")
        assert len(items) == 1
        assert items[0]["employee_name"] == "张三"
        assert items[0]["goal_count"] == 2
        assert items[0]["weighted_progress"] == 80.0

    @pytest.mark.asyncio
    async def test_no_pending_reviews_returns_empty(self):
        session = _mock_session(execute_results=[_FakeResult(rows=[])])
        with _locate(_employee()):
            items = await self_service_service.list_team_reviews(session, "u-1")
        assert items == []

    @pytest.mark.asyncio
    async def test_score_other_reviewer_forbidden(self):
        session = _mock_session()
        session.get = AsyncMock(return_value=_review(reviewer_employee_id="emp-2"))
        with (
            _locate(_employee()),
            pytest.raises(ForbiddenError),
        ):
            await self_service_service.submit_team_review_score(
                session, "u-1", "rev-1", score=Decimal("80"), rating="A"
            )

    @pytest.mark.asyncio
    async def test_score_delegates_to_perf_service(self):
        session = _mock_session()
        session.get = AsyncMock(
            side_effect=[_review(reviewer_employee_id="emp-1"), _employee(), _cycle(status="scoring")]
        )
        updated = _review(score=Decimal("88.00"), rating="A")
        with (
            _locate(_employee()),
            patch(
                "hr.services.self_service_service.perf_review_service.submit_score",
                new=AsyncMock(return_value=updated),
            ) as submit_score,
            patch(
                "hr.services.self_service_service.perf_review_service.to_response",
                new=lambda review, **kwargs: {"id": str(review.id), "score": review.score},
            ),
        ):
            result = await self_service_service.submit_team_review_score(
                session, "u-1", "rev-1", score=Decimal("88"), rating="A"
            )
        submit_score.assert_awaited_once_with(
            session, "rev-1", score=Decimal("88"), rating="A", self_score=None
        )
        assert result["score"] == Decimal("88.00")
