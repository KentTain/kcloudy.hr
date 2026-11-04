"""职级薪带服务：带宽对照 / 版本生效区间（新建自动闭合 + 重叠拒绝）"""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.ctx import get_tenant_id
from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError

from hr.models import SalaryBand
from hr.schemas.salary import SalaryBandCreate, SalaryBandResponse, SalaryBandUpdate


class SalaryBandService:
    """薪带业务（同职级同一时段仅一个生效版本，历史版本只读）"""

    async def list_bands(
        self,
        session: AsyncSession,
        *,
        job_level: str | None = None,
        effective_status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        today = date.today()
        conditions = []
        if job_level:
            conditions.append(SalaryBand.job_level == job_level)
        if effective_status == "active":
            conditions.append(
                SalaryBand.effective_from <= today,
                SalaryBand.effective_to.is_(None) | (SalaryBand.effective_to >= today),
            )
        elif effective_status == "history":
            conditions.append(SalaryBand.effective_to < today)
        elif effective_status == "upcoming":
            conditions.append(SalaryBand.effective_from > today)
        elif effective_status:
            raise BadRequestError("effective_status 仅支持 active/history/upcoming")

        total = (
            await session.execute(
                select(func.count(SalaryBand.id)).where(*conditions)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(SalaryBand)
                .where(*conditions)
                .order_by(
                    SalaryBand.job_level,
                    SalaryBand.effective_from.desc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        items = rows.scalars().all()
        return {
            "total": total,
            "items": [self.to_response(band) for band in items],
        }

    async def create_band(
        self, session: AsyncSession, data: SalaryBandCreate
    ) -> SalaryBand:
        self._validate_amounts(data.min_salary, data.mid_salary, data.max_salary)
        if data.effective_to is None:
            # 先闭合当前开放区间：重叠检查会把 open 区间视作 date.max 而误判冲突
            await self._close_current_version(
                session, data.job_level, data.effective_from
            )
        await self._ensure_no_overlap(
            session, data.job_level, data.effective_from, data.effective_to
        )
        band = SalaryBand(
            tenant_id=get_tenant_id(),
            job_level=data.job_level,
            min_salary=data.min_salary,
            mid_salary=data.mid_salary,
            max_salary=data.max_salary,
            effective_from=data.effective_from,
            effective_to=data.effective_to,
        )
        session.add(band)
        await session.flush()
        return band

    async def get_band(self, session: AsyncSession, band_id: str) -> SalaryBand:
        band = await session.get(SalaryBand, band_id)
        if not band:
            raise NotFoundError(f"薪带 {band_id} 不存在")
        return band

    async def update_band(
        self, session: AsyncSession, band_id: str, data: SalaryBandUpdate
    ) -> SalaryBand:
        band = await self.get_band(session, band_id)
        self._ensure_mutable(band)

        updates = data.model_dump(exclude_unset=True, exclude_none=True)
        for field, value in updates.items():
            setattr(band, field, value)
        self._validate_amounts(band.min_salary, band.mid_salary, band.max_salary)
        await self._ensure_no_overlap(
            session,
            band.job_level,
            band.effective_from,
            band.effective_to,
            exclude_id=str(band.id),
        )
        return band

    async def delete_band(self, session: AsyncSession, band_id: str) -> None:
        band = await self.get_band(session, band_id)
        self._ensure_mutable(band)
        await session.delete(band)

    async def get_active_band(
        self, session: AsyncSession, job_level: str, on_date: date | None = None
    ) -> SalaryBand | None:
        """任一日期点唯一生效薪带（定薪对标/需求薪酬区间参考消费口径）。"""
        on_date = on_date or date.today()
        return (
            await session.execute(
                select(SalaryBand)
                .where(
                    SalaryBand.job_level == job_level,
                    SalaryBand.effective_from <= on_date,
                    SalaryBand.effective_to.is_(None)
                    | (SalaryBand.effective_to >= on_date),
                )
                .order_by(SalaryBand.effective_from.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    # ------------------------------------------------------------------ 内部

    @staticmethod
    def _validate_amounts(min_salary: float, mid_salary: float, max_salary: float) -> None:
        if not (min_salary <= mid_salary <= max_salary):
            raise BadRequestError("带宽须满足 min ≤ mid ≤ max（元/月）")

    @staticmethod
    def _ensure_mutable(band: SalaryBand) -> None:
        """历史版本与当前生效版本只读，仅未生效版本可编辑/删除。"""
        today = date.today()
        if band.effective_from <= today:
            raise ConflictError("仅未生效版本可编辑或删除（历史与当前版本只读）")

    async def _ensure_no_overlap(
        self,
        session: AsyncSession,
        job_level: str,
        effective_from: date,
        effective_to: date | None,
        *,
        exclude_id: str | None = None,
    ) -> None:
        conditions = [SalaryBand.job_level == job_level]
        if exclude_id:
            conditions.append(SalaryBand.id != exclude_id)
        rows = (
            await session.execute(select(SalaryBand).where(*conditions))
        ).scalars().all()
        for band in rows:
            existing_to = band.effective_to or date.max
            new_to = effective_to or date.max
            if effective_from <= existing_to and band.effective_from <= new_to:
                raise ConflictError(
                    f"职级 {job_level} 生效区间与既有版本 "
                    f"({band.effective_from} ~ {band.effective_to or '至今'}) 重叠"
                )

    async def _close_current_version(
        self, session: AsyncSession, job_level: str, new_from: date
    ) -> None:
        """新建当前版本自动闭合旧区间（effective_to = 新版本生效日前一天）。"""
        rows = (
            await session.execute(
                select(SalaryBand).where(
                    SalaryBand.job_level == job_level,
                    SalaryBand.effective_from < new_from,
                    SalaryBand.effective_to.is_(None),
                )
            )
        ).scalars().all()
        for band in rows:
            band.effective_to = new_from - timedelta(days=1)

    def to_response(self, band: SalaryBand) -> SalaryBandResponse:
        return SalaryBandResponse(
            id=str(band.id),
            job_level=band.job_level,
            min_salary=float(band.min_salary),
            mid_salary=float(band.mid_salary),
            max_salary=float(band.max_salary),
            effective_from=band.effective_from,
            effective_to=band.effective_to,
        )


salary_band_service = SalaryBandService()
