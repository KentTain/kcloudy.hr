"""薪酬项控制器 - 管理端

字典 CRUD / 删除保护（被引用只可停用）/ 类别字典读写（转发租户配置）。
权限码 hr:salary_item:read/write/delete。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.schemas.salary import SalaryCategoriesUpdate, SalaryItemCreate, SalaryItemUpdate
from hr.services.salary_item_service import salary_item_service

router = APIRouter()


@router.get("/salary-items")
async def list_salary_items(
    page: int = 1,
    page_size: int = 20,
    category: str | None = None,
    keyword: str | None = None,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:salary_item:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """薪酬项列表（类别筛选 + 编码/名称关键词）"""
    result = await salary_item_service.list_items(
        session, page=page, page_size=page_size, category=category, keyword=keyword
    )
    return ApiResponse.paginated(
        data=result["items"],
        total=result["total"],
        page=page,
        page_size=page_size,
    )


@router.post("/salary-items")
async def create_salary_item(
    data: SalaryItemCreate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:salary_item:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """创建薪酬项（编码租户唯一，创建后不可修改）"""
    item = await salary_item_service.create_item(session, data)
    return ApiResponse.success(data=salary_item_service.to_response(item))


@router.put("/salary-items/{item_id}")
async def update_salary_item(
    item_id: str,
    data: SalaryItemUpdate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:salary_item:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """更新薪酬项（编码不可修改；停用经 can_edit=false）"""
    item = await salary_item_service.update_item(session, item_id, data)
    return ApiResponse.success(data=salary_item_service.to_response(item))


@router.delete("/salary-items/{item_id}")
async def delete_salary_item(
    item_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:salary_item:delete")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """删除薪酬项（被定薪方案或发薪明细引用时拒绝：只可停用）"""
    await salary_item_service.delete_item(session, item_id)
    return ApiResponse.success(msg="删除成功")


@router.get("/salary-setting")
async def get_salary_categories(
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:salary_item:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """薪酬类别字典（转发租户配置 hr_salary_setting.categories）"""
    categories = await salary_item_service.get_categories(session)
    return ApiResponse.success(data=categories.model_dump())


@router.put("/salary-setting")
async def update_salary_categories(
    data: SalaryCategoriesUpdate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:salary_item:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """薪酬类别字典维护（已绑定薪酬项的类别不可删除）"""
    categories = await salary_item_service.update_categories(session, data.categories)
    return ApiResponse.success(data=categories.model_dump())
