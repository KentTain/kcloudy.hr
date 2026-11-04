"""岗位管理控制器 - 管理端

岗位 CRUD + 在岗人数实时统计 + 删除保护（在岗员工 > 0 仅可停用）+ 下拉选项。
权限码 hr:position:read/write/delete。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.schemas.position import (
    PositionCreate,
    PositionPaginatedQuery,
    PositionResponse,
    PositionUpdate,
)
from hr.services.position_service import position_service

router = APIRouter()


@router.get("/positions/options")
async def list_position_options(
    org_id: str | None = None,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:position:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """生效岗位下拉选项（建档/异动弹窗选用）"""
    options = await position_service.list_active_options(session, org_id=org_id)
    return ApiResponse.success(data=options)


@router.get("/positions")
async def list_positions(
    query: PositionPaginatedQuery = Depends(),
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:position:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """岗位列表（在岗人数实时统计，分页）"""
    positions, total = await position_service.list_positions(
        session,
        page=query.page,
        page_size=query.page_size,
        org_id=query.org_id,
        job_level=query.job_level,
        status=query.status,
        keyword=query.keyword,
    )
    return ApiResponse.paginated(
        data=positions,
        total=total,
        page=query.page,
        page_size=query.page_size,
    )


@router.post("/positions")
async def create_position(
    data: PositionCreate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:position:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """创建岗位（编码租户内唯一）"""
    position = await position_service.create_position(session, data)
    return ApiResponse.success(data=position)


@router.get("/positions/{position_id}")
async def get_position(
    position_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:position:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """岗位详情（含在岗人数）"""
    position = await position_service.get_position(session, position_id)
    return ApiResponse.success(data=position)


@router.put("/positions/{position_id}")
async def update_position(
    position_id: str,
    data: PositionUpdate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:position:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """更新岗位（停用后不可被建档与招聘需求选中）"""
    position = await position_service.update_position(session, position_id, data)
    return ApiResponse.success(data=position)


@router.delete("/positions/{position_id}")
async def delete_position(
    position_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:position:delete")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """删除岗位（在岗员工 > 0 不可删除，仅可停用）"""
    await position_service.delete_position(session, position_id)
    return ApiResponse.success(data={"deleted": position_id})
