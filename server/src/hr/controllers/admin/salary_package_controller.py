"""定薪调薪控制器 - 管理端

员工定薪历史 / 调薪（一事一流水：旧区间闭合 + 新区间生成 + salary_change
流水）/ 薪带对标 / 部门职级切片统计。权限码 hr:salary_package:read/write。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.schemas.salary import SalaryPackageCreate
from hr.services.salary_package_service import salary_package_service

router = APIRouter()


@router.get("/employees/{employee_id}/salary-packages")
async def list_employee_salary_packages(
    employee_id: str,
    item_id: str | None = None,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:salary_package:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """员工定薪历史区间（版本倒序，金额元/月）"""
    items = await salary_package_service.list_employee_packages(
        session, employee_id, item_id=item_id
    )
    return ApiResponse.success(data=[item.model_dump() for item in items])


@router.post("/employees/{employee_id}/salary-packages")
async def adjust_salary_package(
    employee_id: str,
    data: SalaryPackageCreate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:salary_package:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """定薪/调薪（区间版本化：生效日后按新旧区间分段折算）"""
    created = await salary_package_service.adjust(session, employee_id, data)
    return ApiResponse.success(
        data=[salary_package_service.to_response(p).model_dump() for p in created]
    )


@router.get("/employees/{employee_id}/salary-comparison")
async def band_comparison(
    employee_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:salary_package:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """薪带对标提示（方案总额相对职级带宽位置）"""
    comparison = await salary_package_service.band_comparison(session, employee_id)
    return ApiResponse.success(data=comparison.model_dump())


@router.get("/salary-packages/comparison")
async def comparison_slices(
    org_id: str | None = None,
    job_level: str | None = None,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:salary_package:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """定薪与薪带对标统计（部门/职级切片，仅聚合口径）"""
    slices = await salary_package_service.comparison_slices(
        session, org_id=org_id, job_level=job_level
    )
    return ApiResponse.success(data=slices)
