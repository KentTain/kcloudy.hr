"""异动管理控制器 - 管理端

异动流水检索（跨员工）+ 发起异动（转正/调岗/职级变更/调薪/离职）。
权限码 hr:employee_change:read/write。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.clients.iam_client import get_iam_client
from framework.common.response import ApiResponse
from framework.database import skip_owner_filter
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.models import EmployeeChange
from hr.schemas.change import (
    ChangeCreate,
    ChangePaginatedQuery,
    ChangeResponse,
    ChangeTransferRequest,
)
from hr.services.change_service import change_service

router = APIRouter()


@router.get("/employee-changes")
async def list_changes(
    query: ChangePaginatedQuery = Depends(),
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:employee_change:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """异动流水分页检索（跨员工；组织筛选按快照 after_data.org_id）"""
    # 管理端全量视角（功能权限已把关），豁免数据归属裁剪
    with skip_owner_filter():
        changes, total = await change_service.list_changes(
            session,
            page=query.page,
            page_size=query.page_size,
            employee_id=query.employee_id,
            change_type=query.change_type,
            org_id=query.org_id,
            keyword=query.keyword,
            start_date=query.start_date,
            end_date=query.end_date,
        )
    return ApiResponse.paginated(
        data=[ChangeResponse.model_validate(c) for c in changes],
        total=total,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/employee-changes/{change_id}")
async def get_change(
    change_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:employee_change:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """异动流水详情"""
    # 管理端全量视角（功能权限已把关），豁免数据归属裁剪
    with skip_owner_filter():
        change = await change_service.get_change(session, change_id)
    return ApiResponse.success(data=ChangeResponse.model_validate(change))


@router.post("/employee-changes")
async def submit_change(
    data: ChangeCreate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:employee_change:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """发起异动（状态机校验 → 更新主档 → 写流水；离职生效发布联动事件）"""
    change = await change_service.submit_change(session, data.employee_id, data)
    return ApiResponse.success(data=change)


@router.post("/employee-changes/{change_id}/transfer")
async def transfer_change(
    change_id: str,
    data: ChangeTransferRequest,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:employee_change:transfer")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """移交业务归属人（owner_id 可变归属；同租户在册校验；before/after 审计留痕）"""
    # 管理端全量视角（功能权限已把关），豁免数据归属裁剪
    with skip_owner_filter():
        existing = await session.get(EmployeeChange, change_id)
        before_owner = existing.owner_id if existing else None
        change = await change_service.transfer_change(
            session, change_id, new_owner_id=data.owner_id
        )
    await get_iam_client().create_audit_log(
        session,
        business_domain="hr",
        operation_type="transfer",
        resource_type="employee_change",
        resource_name=f"员工异动-{change.change_type}",
        resource_id=change_id,
        before_data={"owner_id": before_owner},
        after_data={"owner_id": change.owner_id},
        detail={"operator_id": user_id},
    )
    return ApiResponse.success(data=ChangeResponse.model_validate(change))
