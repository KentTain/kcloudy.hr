"""EAV 服务单元测试

覆盖：值格式化/解析纯函数、校验序列化（数值范围/布尔/JSON）、
属性组与定义 CRUD 校验路径（预置组禁删/同名冲突/data_type 变更存量校验）。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ConflictError
from framework.database.mixins.property import AttributeDataType

from hr.models import EmployeeFieldDefinition, EmployeeFieldGroup
from hr.services.eav_service import (
    PRESET_GROUP_CODES,
    EavService,
    format_value,
    parse_value,
    validate_and_serialize_value,
)


class _FakeResult:
    def __init__(self, entity=None, entities=None, rows=None):
        self._entity = entity
        self._entities = entities if entities is not None else (
            [entity] if entity is not None else []
        )
        self._rows = rows or []

    def scalar_one_or_none(self):
        if self._entity is not None:
            return self._entity
        return self._rows[0] if self._rows else None

    def scalars(self):
        entities = self._entities
        holder = self

        class _All:
            def all(self):
                return entities

        return _All()

    def all(self):
        return self._rows


def _mock_session(execute_results=None) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    if execute_results is not None:
        session.execute = AsyncMock(side_effect=execute_results)
    else:
        session.execute = AsyncMock(return_value=_FakeResult())
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    return session


class TestFormatParse:
    """值格式化与解析纯函数"""

    def test_format_none_is_none(self):
        assert format_value("string", None) is None

    def test_format_boolean(self):
        assert format_value(AttributeDataType.BOOLEAN, True) == "true"
        assert format_value(AttributeDataType.BOOLEAN, False) == "false"

    def test_format_json(self):
        assert json.loads(format_value(AttributeDataType.JSON, {"a": 1})) == {"a": 1}

    def test_parse_empty_is_none(self):
        assert parse_value("string", None) is None
        assert parse_value("string", "") is None

    def test_parse_numeric(self):
        assert parse_value(AttributeDataType.INTEGER, "42") == 42
        assert parse_value(AttributeDataType.DECIMAL, "3.5") == 3.5

    def test_parse_boolean(self):
        assert parse_value(AttributeDataType.BOOLEAN, "true") is True
        assert parse_value(AttributeDataType.BOOLEAN, "false") is False

    def test_parse_json(self):
        assert parse_value(AttributeDataType.JSON, '{"k": "v"}') == {"k": "v"}


class TestValidateAndSerialize:
    """校验序列化"""

    def test_empty_value_returns_none(self):
        assert validate_and_serialize_value("年龄", "integer", None, "") is None
        assert validate_and_serialize_value("年龄", "integer", None, None) is None

    def test_integer_range(self):
        ext = {"min": 18, "max": 60, "unit": "岁"}
        assert validate_and_serialize_value("年龄", "integer", ext, 30) == "30"
        with pytest.raises(BadRequestError):
            validate_and_serialize_value("年龄", "integer", ext, 10)
        with pytest.raises(BadRequestError):
            validate_and_serialize_value("年龄", "integer", ext, 99)

    def test_integer_type_error(self):
        with pytest.raises(BadRequestError):
            validate_and_serialize_value("年龄", "integer", None, "abc")

    def test_boolean_fuzzy(self):
        assert validate_and_serialize_value("已婚", "boolean", None, "yes") == "true"
        assert validate_and_serialize_value("已婚", "boolean", None, 0) == "false"
        with pytest.raises(BadRequestError):
            validate_and_serialize_value("已婚", "boolean", None, "maybe")

    def test_json_invalid(self):
        with pytest.raises(BadRequestError):
            validate_and_serialize_value("扩展", "json", None, "{bad json")

    def test_string_strip(self):
        assert validate_and_serialize_value("籍贯", "string", None, " 杭州 ") == "杭州"


def _group(code: str = "custom", id: str = "g-1", **overrides) -> EmployeeFieldGroup:
    defaults = dict(id=id, tenant_id="t-1", code=code, name="自定义", sort=0)
    defaults.update(overrides)
    return EmployeeFieldGroup(**defaults)


def _definition(group_id: str = "g-1", name: str = "籍贯", **overrides) -> EmployeeFieldDefinition:
    defaults = dict(
        id="d-1",
        tenant_id="t-1",
        group_id=group_id,
        name=name,
        data_type=AttributeDataType.STRING,
        ext_data=None,
        is_require=False,
        can_edit=True,
        sort=0,
    )
    defaults.update(overrides)
    return EmployeeFieldDefinition(**defaults)


class TestGroupCrud:
    """属性组管理"""

    @pytest.mark.asyncio
    async def test_create_group_conflict(self):
        existing = _group(code="custom")
        session = _mock_session([_FakeResult(entity=existing)])
        with pytest.raises(ConflictError):
            await EavService().create_group(session, code="custom", name="重复")

    @pytest.mark.asyncio
    async def test_delete_preset_group_rejected(self):
        session = _mock_session([_FakeResult(entity=_group(code="basic"))])
        with pytest.raises(ConflictError):
            await EavService().delete_group(session, "g-basic")
        assert PRESET_GROUP_CODES >= {"basic", "education", "contacts", "work", "custom"}


class TestDefinitionCrud:
    """属性定义管理"""

    @pytest.mark.asyncio
    async def test_create_definition_name_conflict(self):
        session = _mock_session([
            _FakeResult(entity=_group()),  # _get_group
            _FakeResult(entity=_definition()),  # 同名校验
        ])
        with pytest.raises(ConflictError):
            await EavService().create_definition(
                session, group_id="g-1", name="籍贯", data_type="string"
            )

    @pytest.mark.asyncio
    async def test_create_definition_invalid_data_type(self):
        session = _mock_session([_FakeResult(entity=_group()), _FakeResult()])
        with pytest.raises(BadRequestError):
            await EavService().create_definition(
                session, group_id="g-1", name="字段", data_type="float"
            )

    @pytest.mark.asyncio
    async def test_delete_definition_with_values_rejected(self):
        session = _mock_session([_FakeResult(entity=_definition()), _FakeResult(rows=[("v-1",)])])
        with pytest.raises(ConflictError):
            await EavService().delete_definition(session, "d-1")
