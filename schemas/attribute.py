"""员工扩展属性 DTO（属性组 / 定义 / 实例值）"""

from typing import Any

from framework.schemas import BaseModel


class FieldGroupCreate(BaseModel):
    """属性组创建"""

    code: str
    name: str
    sort: int = 0


class FieldGroupUpdate(BaseModel):
    """属性组更新"""

    name: str | None = None
    sort: int | None = None


class FieldGroupResponse(BaseModel):
    """属性组"""

    id: str
    code: str
    name: str
    sort: int


class FieldDefinitionCreate(BaseModel):
    """属性定义创建"""

    group_id: str
    name: str
    data_type: str
    ext_data: dict[str, Any] | None = None
    is_require: bool = False
    can_edit: bool = True
    sort: int = 0


class FieldDefinitionUpdate(BaseModel):
    """属性定义更新"""

    name: str | None = None
    data_type: str | None = None
    ext_data: dict[str, Any] | None = None
    is_require: bool | None = None
    can_edit: bool | None = None
    sort: int | None = None


class FieldDefinitionResponse(BaseModel):
    """属性定义"""

    id: str
    group_id: str
    name: str
    data_type: str
    ext_data: dict[str, Any] | None = None
    is_require: bool
    can_edit: bool
    sort: int


class AttributeValueItem(BaseModel):
    """定义 + 员工值合并结构（未配置值回 None）"""

    definition_id: str
    group_id: str
    name: str
    data_type: str
    ext_data: dict[str, Any] | None = None
    is_require: bool
    can_edit: bool
    sort: int
    value: Any = None
    raw_value: str | None = None


class EmployeeAttributesSave(BaseModel):
    """员工属性整体保存（只处理出现的键）"""

    values: dict[str, Any]
