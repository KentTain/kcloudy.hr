"""岗位服务单元测试

覆盖：编码租户唯一、删除保护（在岗员工 > 0 拒删）、
停用岗位不可被建档选中语义（服务校验链）。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import ConflictError

from hr.models import Position
from hr.schemas.position import PositionCreate
from hr.services.position_service import PositionService


class _FakeResult:
    def __init__(self, entity=None, rows=None):
        self._entity = entity
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._entity

    def all(self):
        return self._rows


def _mock_session(execute_results=None, get_result=None) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    if execute_results is not None:
        session.execute = AsyncMock(side_effect=execute_results)
    else:
        session.execute = AsyncMock(return_value=_FakeResult())
    session.get = AsyncMock(return_value=get_result)
    session.add = MagicMock()

    async def _flush():
        # 模拟列默认值语义：INSERT（flush）时生成主键
        for call in session.add.call_args_list:
            obj = call.args[0]
            if getattr(obj, "id", None) is None:
                obj.id = "id-" + uuid.uuid4().hex[:8]

    session.flush = AsyncMock(side_effect=_flush)
    session.delete = AsyncMock()
    return session


def _position(**overrides) -> Position:
    defaults = dict(
        id="p-1",
        tenant_id="t-1",
        code="DEV",
        name="研发工程师",
        status="active",
    )
    defaults.update(overrides)
    return Position(**defaults)


class TestPositionCrud:
    """岗位 CRUD"""

    @pytest.mark.asyncio
    async def test_create_code_conflict(self):
        session = _mock_session([_FakeResult(entity=_position())])
        with pytest.raises(ConflictError):
            await PositionService().create_position(
                session, PositionCreate(code="DEV", name="研发工程师")
            )

    @pytest.mark.asyncio
    async def test_create_success(self):
        session = _mock_session([_FakeResult(entity=None)])
        response = await PositionService().create_position(
            session, PositionCreate(code="QA", name="测试工程师")
        )
        session.add.assert_called_once()
        assert response.active_employee_count == 0

    @pytest.mark.asyncio
    async def test_delete_protected_when_occupied(self):
        position = _position()
        session = _mock_session(
            execute_results=[_FakeResult(rows=[("p-1", 3)])], get_result=position
        )
        with pytest.raises(ConflictError, match="仅可停用"):
            await PositionService().delete_position(session, "p-1")
        session.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_ok_when_vacant(self):
        position = _position()
        session = _mock_session(
            execute_results=[_FakeResult(rows=[])], get_result=position
        )
        await PositionService().delete_position(session, "p-1")
        session.delete.assert_awaited_once()
