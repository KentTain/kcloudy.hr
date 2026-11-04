"""绩效评估服务单元测试

覆盖：批量发起去重（scoring 态/在职校验/评估人必填）、评分状态门控（scoring 态/
已校准锁定/评级枚举）、校准留痕（calibrating 态/初评已提交/意见必填/操作人时间）、
收口写系数（calibrated 优先回退/配置映射/兜底 1.0）、tenant_id 显式传递。
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError
from framework.tenant.context import TenantContext

from hr.models import Employee, PerfCycle, PerfGoal, PerfReview
from hr.services.perf_review_service import perf_review_service


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalar_one(self):
        return self._rows[0] if self._rows else 0

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


def _mock_session(get_map=None, execute_results=None) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.flush = AsyncMock()
    added: list = []
    session.add = MagicMock(side_effect=added.append)
    session._added = added
    session.get = AsyncMock(
        side_effect=lambda model, pk: (get_map or {}).get((model.__name__, str(pk)))
    )
    session.execute = AsyncMock(
        side_effect=list(execute_results) if execute_results else []
    )
    return session


def _cycle(**overrides) -> PerfCycle:
    defaults = dict(
        id="cyc-1", tenant_id="t-1", name="2026-H1",
        start_date=date(2026, 1, 1), end_date=date(2026, 6, 30), status="scoring",
    )
    defaults.update(overrides)
    return PerfCycle(**defaults)


def _employee(**overrides) -> Employee:
    defaults = dict(
        id="emp-1", tenant_id="t-1", employee_no="EMP0001",
        name="张三", status="regular",
    )
    defaults.update(overrides)
    return Employee(**defaults)


def _review(**overrides) -> PerfReview:
    defaults = dict(
        id="rev-1", tenant_id="t-1", cycle_id="cyc-1",
        employee_id="emp-1", reviewer_employee_id="emp-9", status="pending",
    )
    defaults.update(overrides)
    return PerfReview(**defaults)


def _patch_perf_setting(values: dict | None = None):
    client = MagicMock()
    client.get_system_setting = AsyncMock(return_value=values)
    return patch("framework.clients.iam_client.get_iam_client", return_value=client)


@pytest.fixture(autouse=True)
def _tenant_context():
    TenantContext.set_tenant_id("t-1")
    yield
    TenantContext.clear()


class TestCreateReviews:
    """批量发起评估（scoring 态去重）"""

    @pytest.mark.asyncio
    async def test_create_sets_tenant_and_pending(self):
        employees = [_employee(), _employee(id="emp-2", employee_no="EMP0002", name="李四")]
        session = _mock_session(
            get_map={("PerfCycle", "cyc-1"): _cycle()},
            execute_results=[_FakeResult(employees), _FakeResult()],
        )
        result = await perf_review_service.create_reviews(
            session, cycle_id="cyc-1",
            items=[
                {"employee_id": "emp-1", "reviewer_employee_id": "emp-9"},
                {"employee_id": "emp-2", "reviewer_employee_id": "emp-9"},
            ],
        )
        assert result == {"cycle_id": "cyc-1", "created": 2, "skipped": 0}
        assert len(session._added) == 2
        assert all(item.tenant_id == "t-1" for item in session._added)
        assert all(item.status == "pending" for item in session._added)

    @pytest.mark.asyncio
    async def test_existing_review_skipped(self):
        employees = [_employee(), _employee(id="emp-2", employee_no="EMP0002", name="李四")]
        session = _mock_session(
            get_map={("PerfCycle", "cyc-1"): _cycle()},
            execute_results=[_FakeResult(employees), _FakeResult(["emp-1"])],
        )
        result = await perf_review_service.create_reviews(
            session, cycle_id="cyc-1",
            items=[
                {"employee_id": "emp-1", "reviewer_employee_id": "emp-9"},
                {"employee_id": "emp-2", "reviewer_employee_id": "emp-9"},
            ],
        )
        assert result["created"] == 1
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_non_scoring_cycle_rejected(self):
        session = _mock_session(
            get_map={("PerfCycle", "cyc-1"): _cycle(status="calibrating")}
        )
        with pytest.raises(ConflictError, match="仅评分中（scoring）可发起评估"):
            await perf_review_service.create_reviews(
                session, cycle_id="cyc-1",
                items=[{"employee_id": "emp-1", "reviewer_employee_id": "emp-9"}],
            )

    @pytest.mark.asyncio
    async def test_cycle_not_found(self):
        session = _mock_session()
        with pytest.raises(NotFoundError, match="不存在"):
            await perf_review_service.create_reviews(
                session, cycle_id="missing",
                items=[{"employee_id": "emp-1", "reviewer_employee_id": "emp-9"}],
            )

    @pytest.mark.asyncio
    async def test_empty_items_rejected(self):
        session = _mock_session(get_map={("PerfCycle", "cyc-1"): _cycle()})
        with pytest.raises(BadRequestError, match="不可为空"):
            await perf_review_service.create_reviews(session, cycle_id="cyc-1", items=[])

    @pytest.mark.asyncio
    async def test_missing_reviewer_rejected(self):
        session = _mock_session(get_map={("PerfCycle", "cyc-1"): _cycle()})
        with pytest.raises(BadRequestError, match="评估人不可为空"):
            await perf_review_service.create_reviews(
                session, cycle_id="cyc-1",
                items=[{"employee_id": "emp-1", "reviewer_employee_id": ""}],
            )

    @pytest.mark.asyncio
    async def test_offboarded_employee_rejected(self):
        session = _mock_session(
            get_map={("PerfCycle", "cyc-1"): _cycle()},
            execute_results=[
                _FakeResult([_employee(status="offboarded", name="王五")]),
                _FakeResult(),
            ],
        )
        with pytest.raises(ConflictError, match="仅在职员工"):
            await perf_review_service.create_reviews(
                session, cycle_id="cyc-1",
                items=[{"employee_id": "emp-1", "reviewer_employee_id": "emp-9"}],
            )


class TestSubmitScore:
    """评分（scoring 态）"""

    @pytest.mark.asyncio
    async def test_score_pending_to_submitted(self):
        review = _review()
        session = _mock_session(
            get_map={("PerfReview", "rev-1"): review,
                     ("PerfCycle", "cyc-1"): _cycle()},
        )
        result = await perf_review_service.submit_score(
            session, "rev-1", score=Decimal("92"), rating="A",
        )
        assert result.status == "submitted"
        assert result.score == Decimal("92")
        assert result.rating == "A"

    @pytest.mark.asyncio
    async def test_resubmit_overrides(self):
        review = _review(status="submitted", score=Decimal("80"), rating="B")
        session = _mock_session(
            get_map={("PerfReview", "rev-1"): review,
                     ("PerfCycle", "cyc-1"): _cycle()},
        )
        result = await perf_review_service.submit_score(
            session, "rev-1", score=Decimal("90"), rating="A",
        )
        assert result.score == Decimal("90")
        assert result.rating == "A"

    @pytest.mark.asyncio
    async def test_calibrated_locked(self):
        review = _review(status="calibrated", rating="B")
        session = _mock_session(get_map={("PerfReview", "rev-1"): review})
        with pytest.raises(ConflictError, match="评分不可再修改"):
            await perf_review_service.submit_score(
                session, "rev-1", score=Decimal("90"), rating="A",
            )

    @pytest.mark.asyncio
    async def test_non_scoring_cycle_rejected(self):
        review = _review()
        session = _mock_session(
            get_map={("PerfReview", "rev-1"): review,
                     ("PerfCycle", "cyc-1"): _cycle(status="calibrating")},
        )
        with pytest.raises(ConflictError, match="仅评分中（scoring）可提交评分"):
            await perf_review_service.submit_score(
                session, "rev-1", score=Decimal("90"), rating="A",
            )

    @pytest.mark.asyncio
    async def test_invalid_rating_rejected(self):
        review = _review()
        session = _mock_session(
            get_map={("PerfReview", "rev-1"): review,
                     ("PerfCycle", "cyc-1"): _cycle()},
        )
        with pytest.raises(BadRequestError, match="评级须为"):
            await perf_review_service.submit_score(
                session, "rev-1", score=Decimal("90"), rating="E",
            )

    @pytest.mark.asyncio
    async def test_review_not_found(self):
        session = _mock_session()
        with pytest.raises(NotFoundError, match="不存在"):
            await perf_review_service.submit_score(
                session, "missing", score=Decimal("90"), rating="A",
            )


class TestCalibrate:
    """校准（calibrating 态 + 初评已提交 + 意见必填留痕）"""

    @pytest.mark.asyncio
    async def test_calibrate_submitted_review(self):
        review = _review(status="submitted", rating="A")
        session = _mock_session(
            get_map={("PerfReview", "rev-1"): review,
                     ("PerfCycle", "cyc-1"): _cycle(status="calibrating")},
        )
        result = await perf_review_service.calibrate(
            session, "rev-1", rating="S",
            comment="  业绩突出，强制分布内调整  ",
            operator_user_id="user-1",
        )
        assert result.status == "calibrated"
        assert result.calibrated_rating == "S"
        assert result.calibrated_by_user_id == "user-1"
        assert result.calibration_comment == "业绩突出，强制分布内调整"
        assert result.calibrated_at is not None
        assert result.rating == "A"

    @pytest.mark.asyncio
    async def test_pending_without_rating_rejected(self):
        review = _review(status="pending")
        session = _mock_session(
            get_map={("PerfReview", "rev-1"): review,
                     ("PerfCycle", "cyc-1"): _cycle(status="calibrating")},
        )
        with pytest.raises(ConflictError, match="尚未提交初评"):
            await perf_review_service.calibrate(
                session, "rev-1", rating="S", comment="调整", operator_user_id="user-1",
            )

    @pytest.mark.asyncio
    async def test_non_calibrating_cycle_rejected(self):
        review = _review(status="submitted", rating="A")
        session = _mock_session(
            get_map={("PerfReview", "rev-1"): review,
                     ("PerfCycle", "cyc-1"): _cycle(status="scoring")},
        )
        with pytest.raises(ConflictError, match="仅校准中（calibrating）可校准"):
            await perf_review_service.calibrate(
                session, "rev-1", rating="S", comment="调整", operator_user_id="user-1",
            )

    @pytest.mark.asyncio
    async def test_comment_required(self):
        review = _review(status="submitted", rating="A")
        session = _mock_session(
            get_map={("PerfReview", "rev-1"): review,
                     ("PerfCycle", "cyc-1"): _cycle(status="calibrating")},
        )
        with pytest.raises(BadRequestError, match="校准意见必填"):
            await perf_review_service.calibrate(
                session, "rev-1", rating="S", comment="  ", operator_user_id="user-1",
            )

    @pytest.mark.asyncio
    async def test_invalid_rating_rejected(self):
        review = _review(status="submitted", rating="A")
        session = _mock_session(
            get_map={("PerfReview", "rev-1"): review,
                     ("PerfCycle", "cyc-1"): _cycle(status="calibrating")},
        )
        with pytest.raises(BadRequestError, match="评级须为"):
            await perf_review_service.calibrate(
                session, "rev-1", rating="X", comment="调整", operator_user_id="user-1",
            )


class TestFinalizeCycle:
    """收口写系数（calibrated 优先回退 + 映射兜底）"""

    @pytest.mark.asyncio
    async def test_coefficient_from_config(self):
        reviews = [_review(calibrated_rating="S", rating="A")]
        session = _mock_session(execute_results=[_FakeResult(reviews)])
        with _patch_perf_setting({"rating_coefficients": {"S": 1.8}}):
            count = await perf_review_service.finalize_cycle(session, "cyc-1")
        assert count == 1
        assert reviews[0].coefficient == Decimal("1.8")

    @pytest.mark.asyncio
    async def test_calibrated_rating_preferred(self):
        reviews = [_review(calibrated_rating="C", rating="A")]
        session = _mock_session(execute_results=[_FakeResult(reviews)])
        with _patch_perf_setting(None):
            await perf_review_service.finalize_cycle(session, "cyc-1")
        assert reviews[0].coefficient == Decimal("0.8")

    @pytest.mark.asyncio
    async def test_builtin_mapping_fallback(self):
        reviews = [_review(rating="A")]
        session = _mock_session(execute_results=[_FakeResult(reviews)])
        with _patch_perf_setting(None):
            await perf_review_service.finalize_cycle(session, "cyc-1")
        assert reviews[0].coefficient == Decimal("1.2")

    @pytest.mark.asyncio
    async def test_no_rating_falls_back_to_one(self):
        reviews = [_review(status="pending")]
        session = _mock_session(execute_results=[_FakeResult(reviews)])
        with _patch_perf_setting(None):
            await perf_review_service.finalize_cycle(session, "cyc-1")
        assert reviews[0].coefficient == Decimal("1.0")

    @pytest.mark.asyncio
    async def test_unknown_rating_falls_back_to_one(self):
        reviews = [_review(rating="X")]
        session = _mock_session(execute_results=[_FakeResult(reviews)])
        with _patch_perf_setting(None):
            await perf_review_service.finalize_cycle(session, "cyc-1")
        assert reviews[0].coefficient == Decimal("1.0")

    @pytest.mark.asyncio
    async def test_empty_cycle_returns_zero(self):
        session = _mock_session(execute_results=[_FakeResult()])
        count = await perf_review_service.finalize_cycle(session, "cyc-1")
        assert count == 0


class TestResolveCoefficient:
    """评级 → 系数解析"""

    def test_config_mapping_wins(self):
        assert perf_review_service.resolve_coefficient(
            {"A": Decimal("1.35")}, "A"
        ) == Decimal("1.35")

    def test_builtin_fallback(self):
        assert perf_review_service.resolve_coefficient({}, "D") == Decimal("0.5")

    def test_none_rating_defaults_one(self):
        assert perf_review_service.resolve_coefficient({}, None) == Decimal("1.0")

    def test_unknown_rating_defaults_one(self):
        assert perf_review_service.resolve_coefficient({}, "Z") == Decimal("1.0")


class TestGoalStatMap:
    """目标达成聚合（加权进度）"""

    @pytest.mark.asyncio
    async def test_weighted_progress_aggregation(self):
        session = _mock_session(
            execute_results=[_FakeResult([("emp-1", 3, Decimal("12000"))])],
        )
        stats = await perf_review_service._goal_stat_map(
            session, "cyc-1", ["emp-1"]
        )
        assert stats["emp-1"] == (3, Decimal("12000"))

    @pytest.mark.asyncio
    async def test_skips_when_no_cycle_or_employees(self):
        session = _mock_session()
        assert await perf_review_service._goal_stat_map(session, None, ["emp-1"]) == {}
        assert await perf_review_service._goal_stat_map(session, "cyc-1", []) == {}

    def test_to_response_weighted_progress(self):
        review = _review(status="submitted", rating="A")
        data = perf_review_service.to_response(
            review,
            employee=_employee(),
            reviewer=_employee(id="emp-9", employee_no="EMP0009", name="上级"),
            cycle_status="scoring",
            goal_stats=(3, Decimal("12000")),
        )
        assert data["goal_count"] == 3
        assert data["weighted_progress"] == 120.0
        assert data["reviewer_name"] == "上级"
        assert data["cycle_status"] == "scoring"
        assert data["status"] == "submitted"
