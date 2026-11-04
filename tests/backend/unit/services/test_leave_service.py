"""假期服务单元测试

覆盖：类型编码租户唯一、计量单位/额度规则白名单、删除保护（被引用只可停用）、
余额惰性初始化（annual_fixed 默认额度 / manual 归零、tenant_id 显式传参）、
额度调整校验（非负/不低于冻结）与审计。
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ConflictError
from framework.tenant.context import TenantContext

from hr.models import Employee, LeaveBalance, LeaveType
from hr.schemas.leave import LeaveTypeCreate
from hr.services.leave_service import leave_service


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
    session.delete = AsyncMock()
    session.get = AsyncMock(
        side_effect=lambda model, pk: (get_map or {}).get((model.__name__, str(pk)))
    )
    session.execute = AsyncMock(
        side_effect=list(execute_results) if execute_results else []
    )
    return session


def _leave_type(**overrides) -> LeaveType:
    defaults = dict(
        id="type-1",
        tenant_id="t-1",
        code="annual",
        name="年假",
        unit="day",
        paid=True,
        quota_rule="annual_fixed",
        default_quota=Decimal("5"),
        status="enabled",
    )
    defaults.update(overrides)
    return LeaveType(**defaults)


def _employee(**overrides) -> Employee:
    defaults = dict(
        id="emp-1", tenant_id="t-1", employee_no="EMP0001",
        name="张三", status="regular",
    )
    defaults.update(overrides)
    return Employee(**defaults)


@pytest.fixture(autouse=True)
def _tenant_context():
    TenantContext.set_tenant_id("t-1")
    yield
    TenantContext.clear()


class TestLeaveType:
    """假期类型"""

    @pytest.mark.asyncio
    async def test_invalid_unit_rejected(self):
        session = _mock_session()
        with pytest.raises(BadRequestError, match="day/hour"):
            await leave_service.create_type(
                session, LeaveTypeCreate(code="a", name="A", unit="week", quota_rule="manual")
            )

    @pytest.mark.asyncio
    async def test_duplicate_code_conflict(self):
        session = _mock_session(execute_results=[_FakeResult(rows=["type-1"])])
        with pytest.raises(ConflictError, match="已存在"):
            await leave_service.create_type(
                session,
                LeaveTypeCreate(code="annual", name="年假", unit="day", quota_rule="manual"),
            )

    @pytest.mark.asyncio
    async def test_create_success_with_tenant(self):
        session = _mock_session(execute_results=[_FakeResult(rows=[])])
        leave_type = await leave_service.create_type(
            session,
            LeaveTypeCreate(
                code="annual", name="年假", unit="day",
                quota_rule="annual_fixed", default_quota=5,
            ),
        )
        assert leave_type.tenant_id == "t-1"
        assert leave_type.status == "enabled"

    @pytest.mark.asyncio
    async def test_delete_protected_when_referenced(self):
        leave_type = _leave_type()
        session = _mock_session(
            get_map={("LeaveType", "type-1"): leave_type},
            execute_results=[_FakeResult(rows=["bal-1"]), _FakeResult(rows=[])],
        )
        with pytest.raises(ConflictError, match="只可停用"):
            await leave_service.delete_type(session, "type-1")

    @pytest.mark.asyncio
    async def test_delete_unreferenced(self):
        leave_type = _leave_type()
        session = _mock_session(
            get_map={("LeaveType", "type-1"): leave_type},
            execute_results=[_FakeResult(rows=[]), _FakeResult(rows=[])],
        )
        await leave_service.delete_type(session, "type-1")
        session.delete.assert_awaited_once_with(leave_type)

    @pytest.mark.asyncio
    async def test_update_rejects_bad_status(self):
        from hr.schemas.leave import LeaveTypeUpdate

        leave_type = _leave_type()
        session = _mock_session(get_map={("LeaveType", "type-1"): leave_type})
        with pytest.raises(BadRequestError, match="enabled/disabled"):
            await leave_service.update_type(
                session, "type-1", LeaveTypeUpdate(status="frozen")
            )


class TestBalanceInit:
    """余额惰性初始化"""

    @pytest.mark.asyncio
    async def test_get_or_create_missing_initializes_by_rule(self):
        leave_type = _leave_type()  # annual_fixed 默认 5
        session = _mock_session(execute_results=[_FakeResult(rows=[])])
        balance = await leave_service.get_or_create_balance(
            session, "emp-1", leave_type, 2026
        )
        assert balance.tenant_id == "t-1"
        assert float(balance.total_quota) == 5.0
        assert balance.year == 2026

    @pytest.mark.asyncio
    async def test_get_or_create_manual_starts_zero(self):
        leave_type = _leave_type(quota_rule="manual", default_quota=None)
        session = _mock_session(execute_results=[_FakeResult(rows=[])])
        balance = await leave_service.get_or_create_balance(
            session, "emp-1", leave_type, 2026
        )
        assert float(balance.total_quota) == 0.0

    @pytest.mark.asyncio
    async def test_ensure_year_balances_fills_missing(self):
        employees = [("emp-1", "EMP0001"), ("emp-2", "EMP0002")]
        enabled = [_leave_type()]
        session = _mock_session(
            execute_results=[
                _FakeResult(rows=employees),            # 在职员工
                _FakeResult(rows=[("emp-1", "type-1")]),  # 已有余额键
            ]
        )
        with patch.object(
            leave_service,
            "list_enabled_types",
            new=AsyncMock(return_value=enabled),
        ):
            await leave_service._ensure_year_balances(session, 2026)
        added = [o for o in session._added if isinstance(o, LeaveBalance)]
        assert len(added) == 1  # 仅补 emp-2
        assert added[0].employee_id == "emp-2"
        assert added[0].tenant_id == "t-1"


class TestAdjustBalance:
    """额度调整"""

    @pytest.mark.asyncio
    async def test_negative_rejected(self):
        session = _mock_session(
            get_map={("LeaveBalance", "bal-1"): LeaveBalance(
                id="bal-1", tenant_id="t-1", employee_id="emp-1",
                leave_type_id="type-1", year=2026, total_quota=5,
            )}
        )
        with pytest.raises(BadRequestError, match="不可为负"):
            await leave_service.adjust_balance(
                session, "bal-1", -1, operator_id="u-1"
            )

    @pytest.mark.asyncio
    async def test_below_frozen_rejected(self):
        session = _mock_session(
            get_map={("LeaveBalance", "bal-1"): LeaveBalance(
                id="bal-1", tenant_id="t-1", employee_id="emp-1",
                leave_type_id="type-1", year=2026, total_quota=10,
                used=Decimal("2"), frozen=Decimal("3"),
            )}
        )
        with pytest.raises(BadRequestError, match="冻结"):
            await leave_service.adjust_balance(
                session, "bal-1", 2, operator_id="u-1"
            )

    @pytest.mark.asyncio
    async def test_success_writes_audit(self):
        balance = LeaveBalance(
            id="bal-1", tenant_id="t-1", employee_id="emp-1",
            leave_type_id="type-1", year=2026, total_quota=5,
            used=Decimal("0"), frozen=Decimal("1"),
        )
        session = _mock_session(get_map={("LeaveBalance", "bal-1"): balance})
        with patch(
            "hr.services.leave_service.get_iam_client"
        ) as iam_factory:
            iam_factory.return_value.create_audit_log = AsyncMock()
            result = await leave_service.adjust_balance(
                session, "bal-1", 8, operator_id="u-1"
            )
        assert float(result.total_quota) == 8.0
        iam_factory.return_value.create_audit_log.assert_awaited_once()
        detail = iam_factory.return_value.create_audit_log.await_args.kwargs["detail"]
        assert detail["operator_id"] == "u-1"
        assert detail["before"]["total_quota"] == 5.0
        assert detail["after"]["total_quota"] == 8.0
