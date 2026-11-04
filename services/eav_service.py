"""员工扩展属性 EAV 服务

值恒存字符串，解析与校验统一经本服务纯函数（语义对齐 iam system_setting_service，
跨模块禁止 import，故复制语义）；业务方禁止自行 json.loads。
"""

import json
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError
from framework.database.mixins.property import AttributeDataType

from hr.models import (
    EmployeeAttributeValue,
    EmployeeFieldDefinition,
    EmployeeFieldGroup,
)

# 预置属性组编码（TenantInitializer seed 同源，管理端不可删除）
PRESET_GROUP_CODES = {"basic", "education", "contacts", "work", "custom"}


def format_value(data_type: str, value: Any) -> str | None:
    """把 Python 值序列化为 value 列的字符串形式（None 恒为未配置）。"""
    if value is None:
        return None
    if data_type == AttributeDataType.BOOLEAN:
        return "true" if value else "false"
    if data_type == AttributeDataType.JSON:
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def parse_value(data_type: str, raw: str | None) -> Any:
    """把 value 列的字符串形式解析回 Python 值（None/空串恒为 None）。"""
    if raw is None or raw == "":
        return None
    if data_type == AttributeDataType.INTEGER:
        return int(raw)
    if data_type == AttributeDataType.DECIMAL:
        return float(raw)
    if data_type == AttributeDataType.BOOLEAN:
        return raw.strip().lower() == "true"
    if data_type == AttributeDataType.JSON:
        return json.loads(raw)
    return raw


def validate_and_serialize_value(
    name: str, data_type: str, ext_data: dict | None, value: Any
) -> str | None:
    """按 data_type/ext_data 校验并序列化为 value 字符串。

    规则：空值返回 None（未配置）；integer/decimal 数值与 min/max 范围；
    boolean 可布尔化；json 可解析；string/date_time 去空格。
    """
    ext = ext_data or {}
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None

    if data_type in (AttributeDataType.INTEGER, AttributeDataType.DECIMAL):
        try:
            number = int(value) if data_type == AttributeDataType.INTEGER else float(value)
        except (TypeError, ValueError) as exc:
            raise BadRequestError(f"属性 {name} 需要数值") from exc
        minimum = ext.get("min")
        maximum = ext.get("max")
        unit = ext.get("unit") or ""
        if minimum is not None and number < minimum:
            raise BadRequestError(f"属性 {name} 不能小于 {minimum}{unit}")
        if maximum is not None and number > maximum:
            raise BadRequestError(f"属性 {name} 不能大于 {maximum}{unit}")
        return str(number)

    if data_type == AttributeDataType.BOOLEAN:
        if isinstance(value, bool):
            return "true" if value else "false"
        text = str(value).strip().lower()
        if text in ("true", "1", "yes", "on"):
            return "true"
        if text in ("false", "0", "no", "off", ""):
            return "false"
        raise BadRequestError(f"属性 {name} 需要布尔值")

    if data_type == AttributeDataType.JSON:
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise BadRequestError(f"属性 {name} 需要合法 JSON") from exc
        else:
            parsed = value
        return json.dumps(parsed, ensure_ascii=False)

    return str(value).strip()


class EavService:
    """员工扩展属性 EAV：属性组/定义管理与实例值读写。"""

    # ── 属性组 ──

    async def list_groups(self, session: AsyncSession) -> list[EmployeeFieldGroup]:
        result = await session.execute(
            select(EmployeeFieldGroup).order_by(EmployeeFieldGroup.sort, EmployeeFieldGroup.created_at)
        )
        return list(result.scalars().all())

    async def create_group(self, session: AsyncSession, *, code: str, name: str, sort: int = 0) -> EmployeeFieldGroup:
        existing = await session.execute(
            select(EmployeeFieldGroup).where(EmployeeFieldGroup.code == code)
        )
        if existing.scalar_one_or_none():
            raise ConflictError(f"属性组编码已存在: {code}")
        group = EmployeeFieldGroup(code=code, name=name, sort=sort)
        session.add(group)
        await session.flush()
        return group

    async def update_group(self, session: AsyncSession, group_id: str, *, name: str | None = None, sort: int | None = None) -> EmployeeFieldGroup:
        group = await self._get_group(session, group_id)
        if name is not None:
            group.name = name
        if sort is not None:
            group.sort = sort
        await session.flush()
        return group

    async def delete_group(self, session: AsyncSession, group_id: str) -> None:
        group = await self._get_group(session, group_id)
        if group.code in PRESET_GROUP_CODES:
            raise ConflictError("预置属性组不可删除")
        # 级联删除组下定义与存量值（定义 FK CASCADE，值 FK CASCADE）
        definition_ids = await self._definition_ids_of_group(session, group.id)
        if definition_ids:
            await session.execute(
                delete(EmployeeAttributeValue).where(
                    EmployeeAttributeValue.definition_id.in_(definition_ids)
                )
            )
            await session.execute(
                delete(EmployeeFieldDefinition).where(EmployeeFieldDefinition.group_id == group.id)
            )
        await session.delete(group)
        await session.flush()

    # ── 属性定义 ──

    async def list_definitions(self, session: AsyncSession, group_id: str | None = None) -> list[EmployeeFieldDefinition]:
        stmt = select(EmployeeFieldDefinition).order_by(
            EmployeeFieldDefinition.sort, EmployeeFieldDefinition.created_at
        )
        if group_id:
            stmt = stmt.where(EmployeeFieldDefinition.group_id == group_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def create_definition(
        self,
        session: AsyncSession,
        *,
        group_id: str,
        name: str,
        data_type: str,
        ext_data: dict | None = None,
        is_require: bool = False,
        can_edit: bool = True,
        sort: int = 0,
    ) -> EmployeeFieldDefinition:
        await self._get_group(session, group_id)
        self._check_data_type(data_type)
        existing = await session.execute(
            select(EmployeeFieldDefinition).where(
                EmployeeFieldDefinition.group_id == group_id,
                EmployeeFieldDefinition.name == name,
            )
        )
        if existing.scalar_one_or_none():
            raise ConflictError(f"该属性组下字段名已存在: {name}")
        definition = EmployeeFieldDefinition(
            group_id=group_id,
            name=name,
            data_type=data_type,
            ext_data=ext_data,
            is_require=is_require,
            can_edit=can_edit,
            sort=sort,
        )
        session.add(definition)
        await session.flush()
        return definition

    async def update_definition(
        self,
        session: AsyncSession,
        definition_id: str,
        *,
        name: str | None = None,
        data_type: str | None = None,
        ext_data: dict | None = None,
        is_require: bool | None = None,
        can_edit: bool | None = None,
        sort: int | None = None,
    ) -> EmployeeFieldDefinition:
        definition = await self._get_definition(session, definition_id)
        if data_type is not None and data_type != definition.data_type:
            self._check_data_type(data_type)
            await self._ensure_existing_values_parsable(session, definition, data_type)
            definition.data_type = data_type
        if name is not None:
            definition.name = name
        if ext_data is not None:
            definition.ext_data = ext_data
        if is_require is not None:
            definition.is_require = is_require
        if can_edit is not None:
            definition.can_edit = can_edit
        if sort is not None:
            definition.sort = sort
        await session.flush()
        return definition

    async def delete_definition(self, session: AsyncSession, definition_id: str) -> None:
        definition = await self._get_definition(session, definition_id)
        values = await session.execute(
            select(EmployeeAttributeValue.id).where(
                EmployeeAttributeValue.definition_id == definition.id
            ).limit(1)
        )
        if values.scalar_one_or_none():
            raise ConflictError("存在员工已填写该属性值，须先清理存量值")
        await session.delete(definition)
        await session.flush()

    # ── 实例值读写 ──

    async def get_employee_attributes(
        self, session: AsyncSession, employee_id: str
    ) -> list[dict]:
        """定义 + 该员工值合并结构（未配置值回 None）。"""
        definitions = await self.list_definitions(session)
        if not definitions:
            return []
        values = await session.execute(
            select(EmployeeAttributeValue).where(
                EmployeeAttributeValue.employee_id == employee_id
            )
        )
        value_map = {v.definition_id: v.value for v in values.scalars().all()}

        return [
            {
                "definition_id": d.id,
                "group_id": d.group_id,
                "name": d.name,
                "data_type": d.data_type,
                "ext_data": d.ext_data,
                "is_require": d.is_require,
                "can_edit": d.can_edit,
                "sort": d.sort,
                "value": parse_value(d.data_type, value_map.get(d.id)),
                "raw_value": value_map.get(d.id),
            }
            for d in definitions
        ]

    async def save_employee_attributes(
        self, session: AsyncSession, employee_id: str, values: dict[str, Any]
    ) -> int:
        """整体保存员工属性值（只处理出现的键），返回写入行数。

        values: {definition_id: value}；按定义校验（必填/类型/范围）后 upsert。
        """
        if not values:
            return 0
        definition_ids = list(values.keys())
        result = await session.execute(
            select(EmployeeFieldDefinition).where(
                EmployeeFieldDefinition.id.in_(definition_ids)
            )
        )
        definitions = {d.id: d for d in result.scalars().all()}

        missing = set(definition_ids) - set(definitions)
        if missing:
            raise NotFoundError(f"属性定义不存在: {', '.join(sorted(missing))}")

        existing_rows = await session.execute(
            select(EmployeeAttributeValue).where(
                EmployeeAttributeValue.employee_id == employee_id,
                EmployeeAttributeValue.definition_id.in_(definition_ids),
            )
        )
        existing_map = {v.definition_id: v for v in existing_rows.scalars().all()}

        written = 0
        for definition_id, value in values.items():
            definition = definitions[definition_id]
            if not definition.can_edit:
                raise BadRequestError(f"属性 {definition.name} 不可编辑")
            serialized = validate_and_serialize_value(
                definition.name, definition.data_type, definition.ext_data, value
            )
            if serialized is None and definition.is_require:
                raise BadRequestError(f"属性 {definition.name} 为必填项")

            row = existing_map.get(definition_id)
            if row is None:
                if serialized is None:
                    continue
                row = EmployeeAttributeValue(
                    employee_id=employee_id, definition_id=definition_id
                )
                session.add(row)
            row.value = serialized
            written += 1

        await session.flush()
        return written

    # ── 内部工具 ──

    async def _get_group(self, session: AsyncSession, group_id: str) -> EmployeeFieldGroup:
        result = await session.execute(
            select(EmployeeFieldGroup).where(EmployeeFieldGroup.id == group_id)
        )
        group = result.scalar_one_or_none()
        if not group:
            raise NotFoundError(f"属性组 {group_id} 不存在")
        return group

    async def _get_definition(
        self, session: AsyncSession, definition_id: str
    ) -> EmployeeFieldDefinition:
        result = await session.execute(
            select(EmployeeFieldDefinition).where(EmployeeFieldDefinition.id == definition_id)
        )
        definition = result.scalar_one_or_none()
        if not definition:
            raise NotFoundError(f"属性定义 {definition_id} 不存在")
        return definition

    @staticmethod
    def _check_data_type(data_type: str) -> None:
        valid = {t.value for t in AttributeDataType}
        if data_type not in valid:
            raise BadRequestError(f"不支持的数据类型: {data_type}（可选 {sorted(valid)}）")

    async def _definition_ids_of_group(self, session: AsyncSession, group_id: str) -> list[str]:
        result = await session.execute(
            select(EmployeeFieldDefinition.id).where(EmployeeFieldDefinition.group_id == group_id)
        )
        return [row[0] for row in result.all()]

    async def _ensure_existing_values_parsable(
        self,
        session: AsyncSession,
        definition: EmployeeFieldDefinition,
        new_data_type: str,
    ) -> None:
        """data_type 变更须校验存量值按新类型可解析。"""
        rows = await session.execute(
            select(EmployeeAttributeValue.value).where(
                EmployeeAttributeValue.definition_id == definition.id
            )
        )
        for (raw,) in rows.all():
            try:
                parse_value(new_data_type, raw)
            except (ValueError, json.JSONDecodeError) as exc:
                raise ConflictError(
                    f"属性 {definition.name} 存量值 {raw!r} 无法按新类型 {new_data_type} 解析"
                ) from exc


eav_service = EavService()
