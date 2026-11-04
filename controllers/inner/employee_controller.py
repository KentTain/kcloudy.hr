"""hr inner 员工接口（供其他模块消费，无认证）

by-user / batch（tenant_id 显式入参防跨租户探测）/ stats / 生效岗位选项。
inner 无租户上下文，控制器内经 TenantContext 显式切换后 ORM 自动过滤才落到目标租户
（先例 iam inner dict_controller）。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel as PydanticBaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import NotFoundError
from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from framework.tenant.context import TenantContext

from hr.schemas.employee import EmployeeResponse
from hr.services.employee_service import employee_service
from hr.services.position_service import position_service

router = APIRouter(prefix="/inner/v1")


class EmployeeBatchRequest(PydanticBaseModel):
    """员工批量查询请求（tenant_id 显式入参防探测）"""

    tenant_id: str
    employee_ids: list[str]


@router.get("/employees/by-user")
async def get_employee_by_user(
    user_id: str,
    tenant_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """按 iam 用户 ID 查员工（员工自助页定位本人档案）"""
    TenantContext.set_tenant_id(tenant_id)
    try:
        employee = await employee_service.get_employee_by_user_id(session, user_id)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return ApiResponse.success(data=EmployeeResponse.model_validate(employee))


@router.post("/employees/batch")
async def get_employees_batch(
    data: EmployeeBatchRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """按 ID 集合批量查员工（batch 端点用 POST 携 body，防 URL 长度与探测）"""
    TenantContext.set_tenant_id(data.tenant_id)
    employees = await employee_service.get_employees_by_ids(
        session, data.employee_ids
    )
    return ApiResponse.success(
        data=[EmployeeResponse.model_validate(e) for e in employees]
    )


@router.get("/employees/stats")
async def get_employee_stats(
    tenant_id: str,
    org_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """员工统计卡（在编/试用/本月新入职/离职率）"""
    TenantContext.set_tenant_id(tenant_id)
    stats = await employee_service.get_stats(session, org_id=org_id)
    return ApiResponse.success(data=stats)


@router.get("/positions/options")
async def get_position_options(
    tenant_id: str,
    org_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """生效岗位下拉选项（招聘需求等跨模块消费）"""
    TenantContext.set_tenant_id(tenant_id)
    options = await position_service.list_active_options(session, org_id=org_id)
    return ApiResponse.success(data=options)
