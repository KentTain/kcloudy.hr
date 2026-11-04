"""定薪调薪服务单元测试

覆盖：区间版本化（旧区间闭合 + 新区间生成 + salary_change 流水）、
生效日期与员工状态校验、停用薪酬项拒绝、薪带对标位置计算。
"""

import contextlib
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError
from framework.tenant.context import TenantContext

from hr.models import Employee, EmployeeSalaryPackage, SalaryBand, SalaryItem
from hr.schemas.salary import SalaryPackageCreate, SalaryPackageItemCreate
from hr.services.salary_package_service import salary_package_service


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

    async def _get(model, pk):
        return (get_map or {}).get((model.__name__, str(pk)))

    session.get = AsyncMock(side_effect=_get)
    session.execute = AsyncMock(
        side_effect=list(execute_results) if execute_results else []
    )
    return session


def _employee(**overrides) -> Employee:
    defaults = dict(
        id="emp-1",
        tenant_id="t-1",
        employee_no="EMP0001",
        name="张三",
        status="regular",
        job_level="P5",
    )
    defaults.update(overrides)
    return Employee(**defaults)


def _item(**overrides) -> SalaryItem:
    defaults = dict(
        id="item-1",
        tenant_id="t-1",
        code="base_monthly",
        name="月度基本工资",
        category="base",
        can_edit=True,
        sort=0,
    )
    defaults.update(overrides)
    return SalaryItem(**defaults)


def _adjust_data(**overrides) -> SalaryPackageCreate:
    defaults = dict(
        items=[SalaryPackageItemCreate(item_id="item-1", amount=22000.0)],
        reason="adjust",
        effective_from=date.today() + timedelta(days=7),
    )
    defaults.update(overrides)
    return SalaryPackageCreate(**defaults)


@contextlib.contextmanager
def _no_change_record():
    with patch(
        "hr.services.salary_package_service.change_service.record_change",
        new=AsyncMock(),
    ) as record:
        yield record


@pytest.fixture(autouse=True)
def _tenant_context():
    TenantContext.set_tenant_id("t-1")
    yield
    TenantContext.clear()


class TestAdjust:
    """定薪/调薪（一事一流水）"""

    @pytest.mark.asyncio
    async def test_closes_old_and_creates_new(self):
        old = EmployeeSalaryPackage(
            id="pkg-old",
            tenant_id="t-1",
            employee_id="emp-1",
            item_id="item-1",
            amount=20000.0,
            reason="hire",
            effective_from=date(2026, 1, 1),
            effective_to=None,
        )
        employee, item = _employee(), _item()
        session = _mock_session(
            get_map={
                ("Employee", "emp-1"): employee,
            },
            execute_results=[
                _FakeResult(rows=[item]),  # 薪酬项加载
                _FakeResult(rows=[old]),   # 当期方案快照（before）
                _FakeResult(rows=[old]),   # 闭合当前区间查询
            ],
        )
        with _no_change_record() as record:
            created = await salary_package_service.adjust(
                session, "emp-1", _adjust_data()
            )
        assert len(created) == 1
        assert old.effective_to == created[0].effective_from - timedelta(days=1)
        assert any(p is created[0] for p in session._added)
        record.assert_awaited_once()
        assert record.await_args.kwargs["change_type"] == "salary_change"

    @pytest.mark.asyncio
    async def test_past_effective_date_rejected(self):
        session = _mock_session(
            get_map={("Employee", "emp-1"): _employee()}
        )
        data = _adjust_data(
            effective_from=date.today() - timedelta(days=1)
        )
        with pytest.raises(BadRequestError, match="早于当日"):
            await salary_package_service.adjust(session, "emp-1", data)

    @pytest.mark.asyncio
    async def test_offboarded_employee_rejected(self):
        session = _mock_session(
            get_map={("Employee", "emp-1"): _employee(status="offboarded")}
        )
        with pytest.raises(ConflictError, match="不可发起"):
            await salary_package_service.adjust(session, "emp-1", _adjust_data())

    @pytest.mark.asyncio
    async def test_disabled_item_rejected(self):
        employee, item = _employee(), _item(can_edit=False)
        session = _mock_session(
            get_map={("Employee", "emp-1"): employee},
            execute_results=[_FakeResult(rows=[item])],
        )
        with pytest.raises(BadRequestError, match="停用"):
            await salary_package_service.adjust(session, "emp-1", _adjust_data())

    @pytest.mark.asyncio
    async def test_missing_item_rejected(self):
        session = _mock_session(
            get_map={("Employee", "emp-1"): _employee()},
            execute_results=[_FakeResult(rows=[])],
        )
        with pytest.raises(NotFoundError, match="薪酬项不存在"):
            await salary_package_service.adjust(session, "emp-1", _adjust_data())


class TestBandComparison:
    """薪带对标位置"""

    @pytest.mark.asyncio
    async def test_below_within_above(self):
        employee = _employee()
        band = SalaryBand(
            id="band-1",
            tenant_id="t-1",
            job_level="P5",
            min_salary=20000.0,
            mid_salary=25000.0,
            max_salary=30000.0,
            effective_from=date(2026, 1, 1),
            effective_to=None,
        )
        pkg_low = EmployeeSalaryPackage(
            id="pkg-1", tenant_id="t-1", employee_id="emp-1", item_id="item-1",
            amount=5000.0, reason="hire", effective_from=date(2026, 1, 1),
        )

        async def _get(model, pk):
            return {("Employee", "emp-1"): employee}.get((model.__name__, str(pk)))

        # below：方案总额 5000 < 下限 20000
        session = AsyncMock(spec=AsyncSession)
        session.get = AsyncMock(side_effect=_get)
        session.execute = AsyncMock(
            side_effect=[
                _FakeResult(rows=[pkg_low]),          # 当期方案行
                _FakeResult(rows=[band]),             # 生效薪带
            ]
        )
        comparison = await salary_package_service.band_comparison(session, "emp-1")
        assert comparison.position == "below"

    @pytest.mark.asyncio
    async def test_no_band_position_none(self):
        employee = _employee(job_level=None)
        pkg = EmployeeSalaryPackage(
            id="pkg-1", tenant_id="t-1", employee_id="emp-1", item_id="item-1",
            amount=5000.0, reason="hire", effective_from=date(2026, 1, 1),
        )
        session = AsyncMock(spec=AsyncSession)
        session.get = AsyncMock(return_value=employee)
        session.execute = AsyncMock(
            side_effect=[
                _FakeResult(rows=[pkg]),
                _FakeResult(rows=[]),  # 无生效薪带（job_level 为空不查，防御返回空）
            ]
        )
        comparison = await salary_package_service.band_comparison(session, "emp-1")
        assert comparison.position == "none"

    @pytest.mark.asyncio
    async def test_employee_not_found(self):
        session = _mock_session()
        with pytest.raises(NotFoundError):
            await salary_package_service.band_comparison(session, "emp-404")
