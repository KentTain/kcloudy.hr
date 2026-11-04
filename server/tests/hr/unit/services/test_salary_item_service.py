"""薪酬项服务单元测试

覆盖：编码租户唯一、删除保护（被定薪方案/发薪明细引用只可停用）、
停用启用、类别字典读写与绑定删除保护。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import ConflictError
from framework.tenant.context import TenantContext

from hr.models import EmployeeSalaryPackage, PayrollEntry, SalaryItem
from hr.schemas.salary import SalaryCategoriesUpdate, SalaryItemCreate, SalaryItemUpdate
from hr.services.salary_item_service import salary_item_service


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

    async def _get(model, pk):
        return (get_map or {}).get((model.__name__, str(pk)))

    session.get = AsyncMock(side_effect=_get)
    session.execute = AsyncMock(
        side_effect=list(execute_results) if execute_results else []
    )
    return session


def _item(**overrides) -> SalaryItem:
    defaults = dict(
        id="item-1",
        tenant_id="t-1",
        code="base_monthly",
        name="月度基本工资",
        category="base",
        ext_data={"monthly_fixed": True},
        can_edit=True,
        sort=0,
    )
    defaults.update(overrides)
    return SalaryItem(**defaults)


@pytest.fixture(autouse=True)
def _tenant_context():
    TenantContext.set_tenant_id("t-1")
    yield
    TenantContext.clear()


class TestCreateItem:
    """字典创建"""

    @pytest.mark.asyncio
    async def test_duplicate_code_conflict(self):
        session = _mock_session(execute_results=[_FakeResult(rows=[1])])
        data = SalaryItemCreate(code="base_monthly", name="重复", category="base")
        with pytest.raises(ConflictError, match="已存在"):
            await salary_item_service.create_item(session, data)

    @pytest.mark.asyncio
    async def test_success(self):
        session = _mock_session(execute_results=[_FakeResult(rows=[])])
        data = SalaryItemCreate(
            code="commission",
            name="提成",
            category="commission",
            ext_data={"monthly_fixed": False},
        )
        item = await salary_item_service.create_item(session, data)
        assert item.code == "commission"
        assert any(i is item for i in session._added)


class TestDeleteProtection:
    """删除保护：被引用只可停用"""

    @pytest.mark.asyncio
    async def test_referenced_by_package_conflict(self):
        session = _mock_session(
            get_map={("SalaryItem", "item-1"): _item()},
            execute_results=[
                _FakeResult(rows=["pkg-row"]),
                _FakeResult(rows=[]),
            ],
        )
        with pytest.raises(ConflictError, match="只可停用"):
            await salary_item_service.delete_item(session, "item-1")
        session.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_referenced_by_payroll_entry_conflict(self):
        session = _mock_session(
            get_map={("SalaryItem", "item-1"): _item()},
            execute_results=[
                _FakeResult(rows=[]),
                _FakeResult(rows=["entry-row"]),
            ],
        )
        with pytest.raises(ConflictError, match="只可停用"):
            await salary_item_service.delete_item(session, "item-1")

    @pytest.mark.asyncio
    async def test_unreferenced_deleted(self):
        session = _mock_session(
            get_map={("SalaryItem", "item-1"): _item()},
            execute_results=[_FakeResult(rows=[]), _FakeResult(rows=[])],
        )
        await salary_item_service.delete_item(session, "item-1")
        session.delete.assert_awaited_once()


class TestUpdateItem:
    """停用/启用与规则更新"""

    @pytest.mark.asyncio
    async def test_disable(self):
        item = _item()
        session = _mock_session(get_map={("SalaryItem", "item-1"): item})
        result = await salary_item_service.update_item(
            session, "item-1", SalaryItemUpdate(can_edit=False)
        )
        assert result.can_edit is False


class TestCategories:
    """类别字典（租户配置转发）"""

    @pytest.mark.asyncio
    async def test_update_rejects_removing_bound_category(self):
        bound = _FakeResult(rows=["base"])
        session = _mock_session(execute_results=[bound])
        with patch(
            "framework.clients.iam_client.get_iam_client"
        ) as client_factory:
            client_factory.return_value.save_system_setting = AsyncMock()
            with pytest.raises(ConflictError, match="不可删除"):
                await salary_item_service.update_categories(
                    session, SalaryCategoriesUpdate(categories=["bonus"]).categories
                )
            client_factory.return_value.save_system_setting.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_saves_to_setting(self):
        session = _mock_session(execute_results=[_FakeResult(rows=[])])
        with patch(
            "framework.clients.iam_client.get_iam_client"
        ) as client_factory:
            client_factory.return_value.save_system_setting = AsyncMock()
            result = await salary_item_service.update_categories(
                session, ["base", "commission"]
            )
        assert result.categories == ["base", "commission"]
        client_factory.return_value.save_system_setting.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_falls_back_to_defaults(self):
        session = _mock_session()
        with patch(
            "framework.clients.iam_client.get_iam_client"
        ) as client_factory:
            client_factory.return_value.get_system_setting = AsyncMock(
                return_value=None
            )
            result = await salary_item_service.get_categories(session)
        assert result.categories == [
            "base",
            "performance",
            "bonus",
            "subsidy",
            "deduction",
        ]
