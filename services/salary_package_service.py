"""定薪调薪服务：区间版本化（一事一流水）/ 薪带对标 / 切片对标统计"""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.ctx import get_tenant_id
from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError

from hr.models import (
    Employee,
    EmployeeSalaryPackage,
    SalaryItem,
)
from hr.schemas.salary import (
    BandComparison,
    SalaryPackageCreate,
    SalaryPackageResponse,
)
from hr.services.change_service import change_service
from hr.services.salary_band_service import salary_band_service

_VALID_REASONS = {"hire", "adjust", "promotion", "perf"}


class SalaryPackageService:
    """定薪调薪业务（金额一律元 DECIMAL(12,2)）"""

    # ── 定薪历史 / 调薪 ──

    async def list_employee_packages(
        self, session: AsyncSession, employee_id: str, *, item_id: str | None = None
    ) -> list[SalaryPackageResponse]:
        """员工定薪历史区间（版本倒序；item_id 过滤单薪酬项）。"""
        conditions = [EmployeeSalaryPackage.employee_id == employee_id]
        if item_id:
            conditions.append(EmployeeSalaryPackage.item_id == item_id)
        rows = (
            await session.execute(
                select(EmployeeSalaryPackage, SalaryItem)
                .join(SalaryItem, EmployeeSalaryPackage.item_id == SalaryItem.id)
                .where(*conditions)
                .order_by(
                    EmployeeSalaryPackage.effective_from.desc(),
                    EmployeeSalaryPackage.created_at.desc(),
                )
            )
        ).all()
        return [
            self.to_response(package, item)
            for package, item in rows
        ]

    async def adjust(
        self, session: AsyncSession, employee_id: str, data: SalaryPackageCreate
    ) -> list[EmployeeSalaryPackage]:
        """定薪/调薪（一事一流水）：逐薪酬项闭合旧区间 + 生成新区间 +
        salary_change 异动流水。

        生效日期不可早于当日；仅在职员工（probation/regular/intern）可发起。
        """
        employee = await session.get(Employee, employee_id)
        if not employee:
            raise NotFoundError(f"员工 {employee_id} 不存在")
        if employee.status not in ("probation", "regular", "intern"):
            raise ConflictError(
                f"员工当前状态 {employee.status} 不可发起定薪/调薪"
            )
        if data.reason not in _VALID_REASONS:
            raise BadRequestError(f"定薪原因须为 {'/'.join(sorted(_VALID_REASONS))}")
        if data.effective_from < date.today():
            raise BadRequestError("生效日期不可早于当日")
        if not data.items:
            raise BadRequestError("薪酬方案不可为空")

        item_ids = [i.item_id for i in data.items]
        item_rows = (
            await session.execute(
                select(SalaryItem).where(SalaryItem.id.in_(item_ids))
            )
        ).scalars().all()
        items_by_id = {str(item.id): item for item in item_rows}
        missing = set(item_ids) - set(items_by_id)
        if missing:
            raise NotFoundError(f"薪酬项不存在: {','.join(sorted(missing))}")
        disabled = [item.code for item in item_rows if not item.can_edit]
        if disabled:
            raise BadRequestError(f"薪酬项已停用: {','.join(disabled)}")

        before_snapshot = await self._active_snapshot(
            session, employee_id, data.effective_from
        )
        created: list[EmployeeSalaryPackage] = []
        seen_items: set[str] = set()
        for line in data.items:
            if line.item_id in seen_items:
                raise BadRequestError(
                    f"薪酬方案中薪酬项 {items_by_id[line.item_id].code} 重复"
                )
            seen_items.add(line.item_id)
            await self._close_current(
                session, employee_id, line.item_id, data.effective_from
            )
            package = EmployeeSalaryPackage(
                tenant_id=get_tenant_id(),
                employee_id=employee_id,
                item_id=line.item_id,
                amount=line.amount,
                reason=data.reason,
                effective_from=data.effective_from,
            )
            session.add(package)
            created.append(package)

        await change_service.record_change(
            session,
            employee=employee,
            change_type="salary_change",
            before_data=before_snapshot,
            after_data={
                str(line.item_id): line.amount for line in data.items
            },
            effective_date=data.effective_from,
        )
        await session.flush()
        return created

    # ── 薪带对标 ──

    async def band_comparison(
        self, session: AsyncSession, employee_id: str
    ) -> BandComparison:
        """方案总额相对职级带宽的位置（below/within/above/none）。"""
        employee = await session.get(Employee, employee_id)
        if not employee:
            raise NotFoundError(f"员工 {employee_id} 不存在")
        total = await self._active_total(
            session, employee_id, date.today()
        )
        band = None
        if employee.job_level:
            band = await salary_band_service.get_active_band(
                session, employee.job_level
            )
        if band is None:
            return BandComparison(
                job_level=employee.job_level or "",
                total=total,
                position="none",
            )
        position = "within"
        if total < float(band.min_salary):
            position = "below"
        elif total > float(band.max_salary):
            position = "above"
        return BandComparison(
            job_level=employee.job_level,
            total=total,
            band_min=float(band.min_salary),
            band_max=float(band.max_salary),
            position=position,
        )

    async def comparison_slices(
        self,
        session: AsyncSession,
        *,
        org_id: str | None = None,
        job_level: str | None = None,
    ) -> list[dict]:
        """定薪与薪带对标统计（职级切片：人数 / 平均方案总额 / 生效带宽）。"""
        conditions = [Employee.status.in_(["probation", "regular", "intern"])]
        if org_id:
            conditions.append(Employee.org_id == org_id)
        if job_level:
            conditions.append(Employee.job_level == job_level)
        employees = (
            await session.execute(select(Employee).where(*conditions))
        ).scalars().all()

        groups: dict[str, list[Employee]] = {}
        for employee in employees:
            if not employee.job_level:
                continue
            groups.setdefault(employee.job_level, []).append(employee)

        slices: list[dict] = []
        for level, members in sorted(groups.items()):
            totals = [
                await self._active_total(session, str(m.id), date.today())
                for m in members
            ]
            band = await salary_band_service.get_active_band(session, level)
            slices.append(
                {
                    "job_level": level,
                    "org_id": org_id,
                    "employee_count": len(members),
                    "avg_total": round(sum(totals) / len(totals), 2),
                    "band_min": float(band.min_salary) if band else None,
                    "band_max": float(band.max_salary) if band else None,
                }
            )
        return slices

    # ------------------------------------------------------------------ 内部

    async def _close_current(
        self,
        session: AsyncSession,
        employee_id: str,
        item_id: str,
        new_from: date,
    ) -> None:
        rows = (
            await session.execute(
                select(EmployeeSalaryPackage).where(
                    EmployeeSalaryPackage.employee_id == employee_id,
                    EmployeeSalaryPackage.item_id == item_id,
                    EmployeeSalaryPackage.effective_from < new_from,
                    EmployeeSalaryPackage.effective_to.is_(None),
                )
            )
        ).scalars().all()
        for package in rows:
            package.effective_to = new_from - timedelta(days=1)

    async def _active_snapshot(
        self, session: AsyncSession, employee_id: str, on_date: date
    ) -> dict:
        rows = await self._active_packages(session, employee_id, on_date)
        return {str(p.item_id): float(p.amount) for p in rows}

    async def _active_total(
        self, session: AsyncSession, employee_id: str, on_date: date
    ) -> float:
        rows = await self._active_packages(session, employee_id, on_date)
        return round(sum(float(p.amount) for p in rows), 2)

    @staticmethod
    async def _active_packages(
        session: AsyncSession, employee_id: str, on_date: date
    ) -> list[EmployeeSalaryPackage]:
        return list(
            (
                await session.execute(
                    select(EmployeeSalaryPackage).where(
                        EmployeeSalaryPackage.employee_id == employee_id,
                        EmployeeSalaryPackage.effective_from <= on_date,
                        EmployeeSalaryPackage.effective_to.is_(None)
                        | (EmployeeSalaryPackage.effective_to >= on_date),
                    )
                )
            ).scalars().all()
        )

    def to_response(
        self, package: EmployeeSalaryPackage, item: SalaryItem | None = None
    ) -> SalaryPackageResponse:
        return SalaryPackageResponse(
            id=str(package.id),
            employee_id=str(package.employee_id),
            item_id=str(package.item_id),
            item_code=item.code if item else None,
            item_name=item.name if item else None,
            category=item.category if item else None,
            amount=float(package.amount),
            reason=package.reason,
            effective_from=package.effective_from,
            effective_to=package.effective_to,
        )


salary_package_service = SalaryPackageService()
