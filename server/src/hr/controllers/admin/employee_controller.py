"""员工管理控制器 - 管理端

花名册 / 建档 / 详情 / 编辑 / 删除 / 统计 / 开通账号 / 批量导入 / 敏感视图 / 扩展属性。
权限码 hr:employee:read/write/delete/sensitive/import；组织名渲染归前端（hr 接口只回 org_id）。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.clients.iam_client import get_iam_client
from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from framework.schemas import BasePaginatedQuery, BaseModel
from iam.dependencies import (
    get_current_user_id,
    optional_permission,
    require_permission,
)

from hr.schemas.attribute import EmployeeAttributesSave
from hr.schemas.change import ChangeResponse
from hr.schemas.employee import (
    EmployeeCreate,
    EmployeeImportRequest,
    EmployeePaginatedQuery,
    EmployeeResponse,
    EmployeeUpdate,
    SensitiveView,
)
from hr.services.change_service import change_service
from hr.services.eav_service import eav_service
from hr.services.employee_service import employee_service

router = APIRouter()


class EmployeeChangeQuery(BasePaginatedQuery):
    """员工异动历史查询"""

    change_type: str | None = None


@router.get("/employees")
async def list_employees(
    query: EmployeePaginatedQuery = Depends(),
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:employee:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """员工花名册（分页；已离职默认不展示，需显式按状态筛选查看）"""
    employees, total = await employee_service.list_employees(
        session,
        page=query.page,
        page_size=query.page_size,
        keyword=query.keyword,
        org_id=query.org_id,
        status=query.status,
        position_id=query.position_id,
        job_level=query.job_level,
    )
    return ApiResponse.paginated(
        data=[EmployeeResponse.model_validate(e) for e in employees],
        total=total,
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/employees/stats")
async def get_employee_stats(
    org_id: str | None = None,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:employee:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """员工统计卡（在编/试用/本月新入职/离职率）"""
    stats = await employee_service.get_stats(session, org_id=org_id)
    return ApiResponse.success(data=stats)


@router.post("/employees/import")
async def import_employees(
    data: EmployeeImportRequest,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:employee:import")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """员工批量导入（dryRun 预检不落库，正式导入逐行容错收集）"""
    result = await employee_service.import_employees(
        session, dry_run=data.dry_run, rows=[row.model_dump() for row in data.rows]
    )
    return ApiResponse.success(data=result)


@router.post("/employees")
async def create_employee(
    data: EmployeeCreate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:employee:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """入职建档（自动取号 + 写 hire 异动流水）"""
    employee = await employee_service.create_employee(session, data)
    return ApiResponse.success(data=EmployeeResponse.model_validate(employee))


@router.get("/employees/{employee_id}")
async def get_employee_detail(
    employee_id: str,
    can_sensitive: bool = Depends(optional_permission("hr:employee:sensitive")),
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:employee:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """员工详情（敏感字段掩码；有 sensitive 权限时掩码置空走明文视图接口）"""
    detail = await employee_service.get_employee_detail(
        session, employee_id, can_sensitive=can_sensitive
    )
    return ApiResponse.success(data=detail)


@router.get("/employees/{employee_id}/sensitive")
async def get_sensitive_view(
    employee_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:employee:sensitive")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """敏感字段明文视图（调用即写审计日志）"""
    view = await employee_service.get_sensitive_view(session, employee_id)
    await get_iam_client().create_audit_log(
        session,
        business_domain="hr",
        operation_type="read",
        resource_type="employee_sensitive",
        resource_name="员工敏感字段明文",
        resource_id=employee_id,
        detail={"operator_id": user_id},
    )
    return ApiResponse.success(data=SensitiveView(**view))


@router.put("/employees/{employee_id}")
async def update_employee(
    employee_id: str,
    data: EmployeeUpdate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:employee:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """员工编辑（组织/岗位/职级/状态变更须走异动办理；敏感字段掩码提交=保留）"""
    employee = await employee_service.update_employee(session, employee_id, data)
    return ApiResponse.success(data=EmployeeResponse.model_validate(employee))


@router.delete("/employees/{employee_id}")
async def delete_employee(
    employee_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:employee:delete")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """删除员工（仅已离职员工可删）"""
    await employee_service.delete_employee(session, employee_id)
    return ApiResponse.success(data={"deleted": employee_id})


@router.post("/employees/{employee_id}/open-account")
async def open_account(
    employee_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:employee:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """开通系统账号（iam 建号回填 user_id，初始密码一次性回显）"""
    result = await employee_service.open_account(session, employee_id)
    return ApiResponse.success(data=result)


@router.get("/employees/{employee_id}/attributes")
async def get_employee_attributes(
    employee_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:employee:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """员工扩展属性（定义 + 值合并结构）"""
    items = await eav_service.get_employee_attributes(session, employee_id)
    return ApiResponse.success(data=items)


@router.put("/employees/{employee_id}/attributes")
async def save_employee_attributes(
    employee_id: str,
    data: EmployeeAttributesSave,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:employee:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """保存员工扩展属性值（按定义校验后 upsert）"""
    written = await eav_service.save_employee_attributes(
        session, employee_id, data.values
    )
    return ApiResponse.success(data={"written": written})


@router.get("/employees/{employee_id}/changes")
async def list_employee_changes(
    employee_id: str,
    query: EmployeeChangeQuery = Depends(),
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:employee_change:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """员工异动历史（倒序流水）"""
    changes, total = await change_service.list_changes(
        session,
        page=query.page,
        page_size=query.page_size,
        employee_id=employee_id,
        change_type=query.change_type,
    )
    return ApiResponse.paginated(
        data=[ChangeResponse.model_validate(c) for c in changes],
        total=total,
        page=query.page,
        page_size=query.page_size,
    )
