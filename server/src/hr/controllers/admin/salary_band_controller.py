"""职级薪带控制器 - 管理端

带宽对照列表（职级/生效状态筛选）/ 新建版本（自动闭合旧区间）/
更新与删除（仅未生效版本）。权限码 hr:salary_band:read/write。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.schemas.salary import SalaryBandCreate, SalaryBandUpdate
from hr.services.salary_band_service import salary_band_service

router = APIRouter()


@router.get("/salary-bands")
async def list_salary_bands(
    page: int = 1,
    page_size: int = 20,
    job_level: str | None = None,
    effective_status: str | None = None,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:salary_band:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """薪带对照表（active=当前生效 / history=历史版本 / upcoming=未生效）"""
    result = await salary_band_service.list_bands(
        session,
        job_level=job_level,
        effective_status=effective_status,
        page=page,
        page_size=page_size,
    )
    return ApiResponse.paginated(
        data=result["items"],
        total=result["total"],
        page=page,
        page_size=page_size,
    )


@router.post("/salary-bands")
async def create_salary_band(
    data: SalaryBandCreate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:salary_band:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """新建薪带版本（min ≤ mid ≤ max；当前版本自动闭合；重叠区间拒绝）"""
    band = await salary_band_service.create_band(session, data)
    return ApiResponse.success(data=salary_band_service.to_response(band))


@router.put("/salary-bands/{band_id}")
async def update_salary_band(
    band_id: str,
    data: SalaryBandUpdate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:salary_band:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """更新薪带（仅未生效版本可编辑）"""
    band = await salary_band_service.update_band(session, band_id, data)
    return ApiResponse.success(data=salary_band_service.to_response(band))


@router.delete("/salary-bands/{band_id}")
async def delete_salary_band(
    band_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:salary_band:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """删除薪带（仅未生效版本可删除）"""
    await salary_band_service.delete_band(session, band_id)
    return ApiResponse.success(msg="删除成功")
