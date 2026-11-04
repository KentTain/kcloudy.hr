"""职级薪带服务单元测试

覆盖：min ≤ mid ≤ max 校验、新建版本自动闭合旧区间、生效区间重叠拒绝、
历史与当前版本只读（仅未生效可改删）、任一日期点唯一生效薪带。
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ConflictError
from framework.tenant.context import TenantContext

from hr.models import SalaryBand
from hr.schemas.salary import SalaryBandCreate, SalaryBandUpdate
from hr.services.salary_band_service import salary_band_service


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
    added: list = []
    session.add = MagicMock(side_effect=added.append)
    session._added = added
    session.delete = AsyncMock()
    session.execute = AsyncMock(
        side_effect=list(execute_results) if execute_results else []
    )
    return session


def _band(**overrides) -> SalaryBand:
    defaults = dict(
        id="band-1",
        tenant_id="t-1",
        job_level="P5",
        min_salary=15000.0,
        mid_salary=20000.0,
        max_salary=25000.0,
        effective_from=date(2026, 1, 1),
        effective_to=None,
    )
    defaults.update(overrides)
    return SalaryBand(**defaults)


@pytest.fixture(autouse=True)
def _tenant_context():
    TenantContext.set_tenant_id("t-1")
    yield
    TenantContext.clear()


class TestCreateBand:
    """新建版本"""

    @pytest.mark.asyncio
    async def test_amounts_ordering_validation(self):
        session = _mock_session()
        data = SalaryBandCreate(
            job_level="P5",
            min_salary=25000.0,
            mid_salary=20000.0,
            max_salary=15000.0,
            effective_from=date(2026, 12, 1),
        )
        with pytest.raises(BadRequestError, match="min ≤ mid ≤ max"):
            await salary_band_service.create_band(session, data)

    @pytest.mark.asyncio
    async def test_overlap_rejected(self):
        existing = _band(
            effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31)
        )
        session = _mock_session(execute_results=[_FakeResult(rows=[existing])])
        data = SalaryBandCreate(
            job_level="P5",
            min_salary=15000.0,
            mid_salary=20000.0,
            max_salary=25000.0,
            effective_from=date(2026, 6, 1),  # 与既有区间重叠
            effective_to=date(2027, 6, 30),
        )
        with pytest.raises(ConflictError, match="重叠"):
            await salary_band_service.create_band(session, data)

    @pytest.mark.asyncio
    async def test_new_current_version_closes_old(self):
        old = _band(id="band-old", effective_from=date(2026, 1, 1), effective_to=None)
        session = _mock_session(execute_results=[
            _FakeResult(rows=[old]),  # 闭合当前版本查询
            _FakeResult(rows=[old]),  # 重叠检查扫全量版本（此时旧区间已闭合，不误判）
        ])
        new_from = date(2027, 1, 1)
        data = SalaryBandCreate(
            job_level="P5",
            min_salary=16000.0,
            mid_salary=21000.0,
            max_salary=26000.0,
            effective_from=new_from,
        )
        band = await salary_band_service.create_band(session, data)
        assert old.effective_to == new_from - timedelta(days=1)
        assert band.effective_to is None
        assert any(b is band for b in session._added)


class TestMutabilityGate:
    """历史与当前版本只读"""

    @pytest.mark.asyncio
    async def test_active_version_not_mutable(self):
        active = _band(
            effective_from=date(2026, 1, 1), effective_to=None
        )  # effective_from 已过 → 当前版本
        session = _mock_session()
        session.get = AsyncMock(return_value=active)
        with pytest.raises(ConflictError, match="只读"):
            await salary_band_service.update_band(
                session, "band-1", SalaryBandUpdate(max_salary=30000.0)
            )

    @pytest.mark.asyncio
    async def test_upcoming_version_mutable(self):
        next_year = date.today().year + 1
        upcoming = _band(
            effective_from=date(next_year, 1, 1), effective_to=None
        )
        session = _mock_session(execute_results=[_FakeResult(rows=[])])  # 重叠检查
        session.get = AsyncMock(return_value=upcoming)
        result = await salary_band_service.update_band(
            session, "band-1", SalaryBandUpdate(max_salary=30000.0)
        )
        assert float(result.max_salary) == 30000.0

    @pytest.mark.asyncio
    async def test_delete_only_upcoming(self):
        active = _band(effective_from=date(2026, 1, 1), effective_to=None)
        session = _mock_session()
        session.get = AsyncMock(return_value=active)
        with pytest.raises(ConflictError, match="只读"):
            await salary_band_service.delete_band(session, "band-1")


class TestActiveBandLookup:
    """任一日期点唯一生效薪带"""

    @pytest.mark.asyncio
    async def test_returns_latest_matching(self):
        session = _mock_session(execute_results=[_FakeResult(rows=[_band()])])
        band = await salary_band_service.get_active_band(session, "P5")
        assert band is not None
        assert band.job_level == "P5"

    @pytest.mark.asyncio
    async def test_none_when_absent(self):
        session = _mock_session(execute_results=[_FakeResult(rows=[])])
        assert await salary_band_service.get_active_band(session, "P9") is None
