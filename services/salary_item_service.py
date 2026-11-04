"""薪酬项服务：字典 CRUD / 删除保护（被引用只可停用）/ 类别字典（租户配置）"""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.ctx import get_tenant_id
from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError

from hr.models import EmployeeSalaryPackage, PayrollEntry, SalaryItem
from hr.schemas.salary import (
    SalaryCategoriesResponse,
    SalaryItemCreate,
    SalaryItemResponse,
    SalaryItemUpdate,
)

_SALARY_SETTING_CODE = "hr_salary_setting"

_DEFAULT_CATEGORIES = ["base", "performance", "bonus", "subsidy", "deduction"]

_CATEGORY_LABELS = {
    "base": "基本工资",
    "performance": "绩效工资",
    "bonus": "奖金",
    "subsidy": "补贴",
    "deduction": "扣款",
}


class SalaryItemService:
    """薪酬项字典业务（不承载金额，金额仅存在于定薪方案与发薪明细）"""

    # ── 字典 CRUD ──

    async def list_items(
        self,
        session: AsyncSession,
        *,
        page: int = 1,
        page_size: int = 20,
        category: str | None = None,
        keyword: str | None = None,
    ) -> dict:
        conditions = []
        if category:
            conditions.append(SalaryItem.category == category)
        if keyword:
            like = f"%{keyword}%"
            conditions.append(
                or_(SalaryItem.code.ilike(like), SalaryItem.name.ilike(like))
            )

        total = (
            await session.execute(
                select(func.count(SalaryItem.id)).where(*conditions)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(SalaryItem)
                .where(*conditions)
                .order_by(SalaryItem.sort, SalaryItem.code)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        items = rows.scalars().all()
        return {
            "total": total,
            "items": [self.to_response(item) for item in items],
        }

    async def create_item(
        self, session: AsyncSession, data: SalaryItemCreate
    ) -> SalaryItem:
        existing = (
            await session.execute(
                select(SalaryItem.id).where(SalaryItem.code == data.code).limit(1)
            )
        ).scalar_one_or_none()
        if existing:
            raise ConflictError(f"薪酬项编码 {data.code} 已存在")
        item = SalaryItem(
            tenant_id=get_tenant_id(),
            code=data.code,
            name=data.name,
            category=data.category,
            ext_data=data.ext_data,
            sort=data.sort,
        )
        session.add(item)
        await session.flush()
        return item

    async def get_item(self, session: AsyncSession, item_id: str) -> SalaryItem:
        item = await session.get(SalaryItem, item_id)
        if not item:
            raise NotFoundError(f"薪酬项 {item_id} 不存在")
        return item

    async def update_item(
        self, session: AsyncSession, item_id: str, data: SalaryItemUpdate
    ) -> SalaryItem:
        item = await self.get_item(session, item_id)
        updates = data.model_dump(exclude_unset=True, exclude_none=True)
        for field, value in updates.items():
            setattr(item, field, value)
        return item

    async def delete_item(self, session: AsyncSession, item_id: str) -> None:
        """删除保护：被定薪方案或发薪明细引用的薪酬项只可停用。"""
        item = await self.get_item(session, item_id)
        referenced = (
            await session.execute(
                select(EmployeeSalaryPackage.id)
                .where(EmployeeSalaryPackage.item_id == item_id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if referenced is None:
            referenced = (
                await session.execute(
                    select(PayrollEntry.id)
                    .where(PayrollEntry.item_id == item_id)
                    .limit(1)
                )
            ).scalar_one_or_none()
        if referenced:
            raise ConflictError(
                f"薪酬项 {item.code} 已被定薪方案或发薪明细引用，只可停用"
            )
        await session.delete(item)

    # ── 类别字典（租户配置 SystemSetting hr_salary_setting.categories）──

    async def get_categories(self, session: AsyncSession) -> SalaryCategoriesResponse:
        values = await self._read_salary_setting(session)
        categories = values.get("categories") if values else None
        if not isinstance(categories, list) or not categories:
            categories = list(_DEFAULT_CATEGORIES)
        return SalaryCategoriesResponse(categories=[str(c) for c in categories])

    async def update_categories(
        self, session: AsyncSession, categories: list[str]
    ) -> SalaryCategoriesResponse:
        if not categories:
            raise BadRequestError("类别清单不可为空")
        if len(set(categories)) != len(categories):
            raise BadRequestError("类别清单存在重复项")

        bound = (
            await session.execute(
                select(SalaryItem.category).distinct().where(
                    SalaryItem.category.in_(categories)
                )
            )
        ).scalars().all()
        removed_bound = set(bound) - set(categories)
        if removed_bound:
            raise ConflictError(
                f"类别 {','.join(sorted(removed_bound))} 已绑定薪酬项，不可删除"
            )

        from framework.clients.iam_client import get_iam_client

        await get_iam_client().save_system_setting(
            session,
            get_tenant_id(),
            _SALARY_SETTING_CODE,
            {"categories": categories},
        )
        return SalaryCategoriesResponse(categories=categories)

    async def _read_salary_setting(self, session: AsyncSession) -> dict | None:
        from framework.clients.iam_client import get_iam_client

        return await get_iam_client().get_system_setting(
            session, get_tenant_id(), _SALARY_SETTING_CODE
        )

    def category_label(self, category: str) -> str:
        return _CATEGORY_LABELS.get(category, category)

    # ── 响应构造 ──

    def to_response(self, item: SalaryItem) -> SalaryItemResponse:
        return SalaryItemResponse(
            id=str(item.id),
            code=item.code,
            name=item.name,
            category=item.category,
            ext_data=item.ext_data,
            can_edit=item.can_edit,
            sort=item.sort,
        )


salary_item_service = SalaryItemService()
