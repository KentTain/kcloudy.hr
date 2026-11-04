"""员工属性配置控制器 - 管理端（EAV 属性组/定义）

属性组 CRUD（预置五组不可删）+ 属性定义 CRUD（data_type 变更校验存量值可解析、
存量值存在禁删）。权限码 hr:field_definition:read/write/delete。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.schemas.attribute import (
    FieldDefinitionCreate,
    FieldDefinitionResponse,
    FieldDefinitionUpdate,
    FieldGroupCreate,
    FieldGroupResponse,
    FieldGroupUpdate,
)
from hr.services.eav_service import eav_service

router = APIRouter()


@router.get("/field-groups")
async def list_field_groups(
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:field_definition:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """属性组列表（预置 + 自建）"""
    groups = await eav_service.list_groups(session)
    return ApiResponse.success(
        data=[FieldGroupResponse.model_validate(g) for g in groups]
    )


@router.post("/field-groups")
async def create_field_group(
    data: FieldGroupCreate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:field_definition:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """创建属性组（编码租户内唯一，预置编码不可复用）"""
    group = await eav_service.create_group(
        session, code=data.code, name=data.name, sort=data.sort
    )
    return ApiResponse.success(data=FieldGroupResponse.model_validate(group))


@router.put("/field-groups/{group_id}")
async def update_field_group(
    group_id: str,
    data: FieldGroupUpdate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:field_definition:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """更新属性组（仅名称与排序）"""
    group = await eav_service.update_group(
        session, group_id, name=data.name, sort=data.sort
    )
    return ApiResponse.success(data=FieldGroupResponse.model_validate(group))


@router.delete("/field-groups/{group_id}")
async def delete_field_group(
    group_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:field_definition:delete")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """删除属性组（预置组不可删；级联清理组下定义与存量值）"""
    await eav_service.delete_group(session, group_id)
    return ApiResponse.success(data={"deleted": group_id})


@router.get("/field-definitions")
async def list_field_definitions(
    group_id: str | None = None,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:field_definition:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """属性定义列表（可按属性组筛选）"""
    definitions = await eav_service.list_definitions(session, group_id=group_id)
    return ApiResponse.success(
        data=[FieldDefinitionResponse.model_validate(d) for d in definitions]
    )


@router.post("/field-definitions")
async def create_field_definition(
    data: FieldDefinitionCreate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:field_definition:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """创建属性定义（同组字段名唯一，data_type 校验）"""
    definition = await eav_service.create_definition(
        session,
        group_id=data.group_id,
        name=data.name,
        data_type=data.data_type,
        ext_data=data.ext_data,
        is_require=data.is_require,
        can_edit=data.can_edit,
        sort=data.sort,
    )
    return ApiResponse.success(data=FieldDefinitionResponse.model_validate(definition))


@router.put("/field-definitions/{definition_id}")
async def update_field_definition(
    definition_id: str,
    data: FieldDefinitionUpdate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:field_definition:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """更新属性定义（data_type 变更须存量值可按新类型解析）"""
    definition = await eav_service.update_definition(
        session,
        definition_id,
        name=data.name,
        data_type=data.data_type,
        ext_data=data.ext_data,
        is_require=data.is_require,
        can_edit=data.can_edit,
        sort=data.sort,
    )
    return ApiResponse.success(data=FieldDefinitionResponse.model_validate(definition))


@router.delete("/field-definitions/{definition_id}")
async def delete_field_definition(
    definition_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:field_definition:delete")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """删除属性定义（存在员工已填值时拒绝）"""
    await eav_service.delete_definition(session, definition_id)
    return ApiResponse.success(data={"deleted": definition_id})
