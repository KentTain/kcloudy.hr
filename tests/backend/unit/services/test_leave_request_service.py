"""请假服务单元测试

覆盖：时长计算（天=闭区间/小时=差值）、提交校验链（在职/类型启用/区间/
年度/重叠/余额充足）、审批状态机（通过=冻结转已用+逐日写考勤、驳回意见
必填+释放冻结、撤销仅本人待审批）。
"""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ConflictError
from framework.tenant.context import TenantContext

from hr.models import Employee, LeaveBalance, LeaveRequest, LeaveType
from hr.schemas.leave import LeaveRequestCreate
from hr.services.leave_request_service import (
    calculate_duration,
    leave_request_service,
)


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


def _employee(**overrides) -> Employee:
    defaults = dict(
        id="emp-1", tenant_id="t-1", employee_no="EMP0001",
        name="张三", status="regular",
    )
    defaults.update(overrides)
    return Employee(**defaults)


def _leave_type(**overrides) -> LeaveType:
    defaults = dict(
        id="type-1", tenant_id="t-1", code="annual", name="年假",
        unit="day", paid=True, quota_rule="annual_fixed",
        default_quota=Decimal("5"), status="enabled",
    )
    defaults.update(overrides)
    return LeaveType(**defaults)


def _balance(**overrides) -> LeaveBalance:
    defaults = dict(
        id="bal-1", tenant_id="t-1", employee_id="emp-1",
        leave_type_id="type-1", year=2026,
        total_quota=Decimal("10"), used=Decimal("2"), frozen=Decimal("0"),
    )
    defaults.update(overrides)
    return LeaveBalance(**defaults)


def _request(**overrides) -> LeaveRequest:
    defaults = dict(
        id="req-1", tenant_id="t-1", employee_id="emp-1",
        leave_type_id="type-1",
        start_time=datetime(2026, 10, 20, 0, 0),
        end_time=datetime(2026, 10, 21, 23, 59),
        duration=2.0, reason="家事", status="pending",
    )
    defaults.update(overrides)
    return LeaveRequest(**defaults)


def _create_data(**overrides) -> LeaveRequestCreate:
    defaults = dict(
        leave_type_id="type-1",
        start_time=datetime(2026, 10, 20, 0, 0),
        end_time=datetime(2026, 10, 21, 0, 0),
        reason="家事",
    )
    defaults.update(overrides)
    return LeaveRequestCreate(**defaults)


@pytest.fixture(autouse=True)
def _tenant_context():
    TenantContext.set_tenant_id("t-1")
    yield
    TenantContext.clear()


class TestCalculateDuration:
    """时长计算"""

    def test_day_inclusive(self):
        assert (
            calculate_duration(
                "day",
                datetime(2026, 10, 20, 9, 0),
                datetime(2026, 10, 21, 18, 0),
            )
            == 2.0
        )

    def test_hour_difference(self):
        assert (
            calculate_duration(
                "hour",
                datetime(2026, 10, 20, 9, 0),
                datetime(2026, 10, 20, 13, 30),
            )
            == 4.5
        )


class TestSubmitRequest:
    """提交校验链"""

    @pytest.mark.asyncio
    async def test_offboarded_rejected(self):
        session = _mock_session(
            get_map={("Employee", "emp-1"): _employee(status="offboarded")}
        )
        with pytest.raises(ConflictError, match="在职"):
            await leave_request_service.submit_request(session, "emp-1", _create_data())

    @pytest.mark.asyncio
    async def test_end_before_start_rejected(self):
        session = _mock_session(get_map={("Employee", "emp-1"): _employee()})
        with pytest.raises(BadRequestError, match="晚于"):
            await leave_request_service.submit_request(
                session,
                "emp-1",
                _create_data(
                    start_time=datetime(2026, 10, 21, 0, 0),
                    end_time=datetime(2026, 10, 20, 0, 0),
                ),
            )

    @pytest.mark.asyncio
    async def test_cross_year_rejected(self):
        session = _mock_session(get_map={("Employee", "emp-1"): _employee()})
        with pytest.raises(BadRequestError, match="年度"):
            await leave_request_service.submit_request(
                session,
                "emp-1",
                _create_data(end_time=datetime(2027, 1, 2, 0, 0)),
            )

    @pytest.mark.asyncio
    async def test_disabled_type_rejected(self):
        session = _mock_session(
            get_map={
                ("Employee", "emp-1"): _employee(),
                ("LeaveType", "type-1"): _leave_type(status="disabled"),
            }
        )
        with pytest.raises(BadRequestError, match="停用"):
            await leave_request_service.submit_request(session, "emp-1", _create_data())

    @pytest.mark.asyncio
    async def test_overlap_rejected(self):
        session = _mock_session(
            get_map={
                ("Employee", "emp-1"): _employee(),
                ("LeaveType", "type-1"): _leave_type(),
            },
            execute_results=[_FakeResult(rows=["req-0"])],  # 重叠单
        )
        with pytest.raises(ConflictError, match="重叠"):
            await leave_request_service.submit_request(session, "emp-1", _create_data())

    @pytest.mark.asyncio
    async def test_insufficient_balance_rejected(self):
        session = _mock_session(
            get_map={
                ("Employee", "emp-1"): _employee(),
                ("LeaveType", "type-1"): _leave_type(),
            },
            execute_results=[
                _FakeResult(rows=[]),     # 无重叠
                _FakeResult(rows=[_balance(total_quota=Decimal("1"))]),  # 可用仅 1
            ],
        )
        with pytest.raises(BadRequestError, match="余额不足"):
            await leave_request_service.submit_request(session, "emp-1", _create_data())

    @pytest.mark.asyncio
    async def test_success_freezes_balance(self):
        balance = _balance()
        session = _mock_session(
            get_map={
                ("Employee", "emp-1"): _employee(),
                ("LeaveType", "type-1"): _leave_type(),
            },
            execute_results=[
                _FakeResult(rows=[]),      # 无重叠
                _FakeResult(rows=[balance]),
            ],
        )
        request = await leave_request_service.submit_request(session, "emp-1", _create_data())
        assert request.status == "pending"
        assert request.tenant_id == "t-1"
        assert float(balance.frozen) == 2.0  # 冻结 2 天


class TestApprove:
    """审批通过"""

    @pytest.mark.asyncio
    async def test_non_pending_rejected(self):
        session = _mock_session(
            get_map={("LeaveRequest", "req-1"): _request(status="approved")}
        )
        with pytest.raises(ConflictError, match="不可审批"):
            await leave_request_service.approve(session, "req-1", approver_id="u-1")

    @pytest.mark.asyncio
    async def test_concurrent_frozen_change_rejected(self):
        session = _mock_session(
            get_map={
                ("LeaveRequest", "req-1"): _request(),
                ("LeaveBalance", "bal-1"): _balance(frozen=Decimal("1")),
            },
            execute_results=[_FakeResult(rows=[_balance(frozen=Decimal("1"))])],
        )
        with pytest.raises(ConflictError, match="并发调整"):
            await leave_request_service.approve(session, "req-1", approver_id="u-1")

    @pytest.mark.asyncio
    async def test_approve_moves_frozen_to_used_and_writes_attendance(self):
        request = _request()
        balance = _balance(frozen=Decimal("2"))
        session = _mock_session(
            get_map={
                ("LeaveRequest", "req-1"): request,
                ("LeaveType", "type-1"): _leave_type(),
            },
            execute_results=[_FakeResult(rows=[balance])],
        )
        with patch(
            "hr.services.leave_request_service.attendance_service.upsert_record",
            new=AsyncMock(),
        ) as upsert:
            result = await leave_request_service.approve(
                session, "req-1", approver_id="u-1", comment="同意"
            )
        assert result.status == "approved"
        assert result.approver_id == "u-1"
        assert float(balance.frozen) == 0.0
        assert float(balance.used) == 4.0
        # 10-20、10-21 逐日写考勤（status=leave、source=leave）
        assert upsert.await_count == 2
        kwargs = upsert.await_args_list[0].kwargs
        assert kwargs["status"] == "leave"
        assert kwargs["source"] == "leave"
        assert kwargs["work_date"] == date(2026, 10, 20)


class TestRejectAndCancel:
    """驳回与撤销"""

    @pytest.mark.asyncio
    async def test_reject_requires_comment(self):
        session = _mock_session()
        with pytest.raises(BadRequestError, match="意见"):
            await leave_request_service.reject(
                session, "req-1", approver_id="u-1", comment="  "
            )

    @pytest.mark.asyncio
    async def test_reject_releases_frozen(self):
        request = _request()
        balance = _balance(frozen=Decimal("2"))
        session = _mock_session(
            get_map={("LeaveRequest", "req-1"): request},
            execute_results=[_FakeResult(rows=[balance])],
        )
        result = await leave_request_service.reject(
            session, "req-1", approver_id="u-1", comment="人手不足"
        )
        assert result.status == "rejected"
        assert float(balance.frozen) == 0.0

    @pytest.mark.asyncio
    async def test_cancel_only_own_pending(self):
        session = _mock_session(
            get_map={("LeaveRequest", "req-1"): _request(employee_id="emp-other")}
        )
        with pytest.raises(ConflictError, match="本人"):
            await leave_request_service.cancel_request(session, "req-1", "emp-1")

    @pytest.mark.asyncio
    async def test_cancel_processed_rejected(self):
        session = _mock_session(
            get_map={("LeaveRequest", "req-1"): _request(status="approved")}
        )
        with pytest.raises(ConflictError, match="待审批"):
            await leave_request_service.cancel_request(session, "req-1", "emp-1")

    @pytest.mark.asyncio
    async def test_cancel_releases_frozen(self):
        request = _request()
        balance = _balance(frozen=Decimal("2"))
        session = _mock_session(
            get_map={("LeaveRequest", "req-1"): request},
            execute_results=[_FakeResult(rows=[balance])],
        )
        result = await leave_request_service.cancel_request(session, "req-1", "emp-1")
        assert result.status == "cancelled"
        assert float(balance.frozen) == 0.0
