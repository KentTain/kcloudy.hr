"""岗位服务：岗位 CRUD + 在岗人数实时统计 + 删除保护"""

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError

from hr.models import Employee, Position
from hr.schemas.position import PositionCreate, PositionResponse, PositionUpdate

_logger = logger.bind(name=__name__)


class PositionService:
    """岗位业务"""

    async def list_positions(
        self,
        session: AsyncSession,
        *,
        page: int,
        page_size: int,
        org_id: str | None = None,
        job_level: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[PositionResponse], int]:
        conditions = []
        if org_id:
            conditions.append(Position.org_id == org_id)
        if job_level:
            conditions.append(Position.job_level == job_level)
        if status:
            conditions.append(Position.status == status)
        if keyword:
            like = f"%{keyword}%"
            conditions.append(
                Position.code.ilike(like) | Position.name.ilike(like)
            )

        total = (
            await session.execute(
                select(func.count(Position.id)).where(*conditions)
            )
        ).scalar_one()

        result = await session.execute(
            select(Position)
            .where(*conditions)
            .order_by(Position.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        positions = list(result.scalars().all())
        counts = await self._active_counts(session, [p.id for p in positions])
        return [
            self._to_response(position, counts.get(position.id, 0))
            for position in positions
        ], total

    async def list_active_options(
        self, session: AsyncSession, *, org_id: str | None = None
    ) -> list[PositionResponse]:
        """生效岗位下拉选项（建档/异动弹窗选用）。"""
        conditions = [Position.status == "active"]
        if org_id:
            conditions.append(Position.org_id == org_id)
        result = await session.execute(
            select(Position).where(*conditions).order_by(Position.code)
        )
        positions = list(result.scalars().all())
        counts = await self._active_counts(session, [p.id for p in positions])
        return [self._to_response(p, counts.get(p.id, 0)) for p in positions]

    async def get_position(self, session: AsyncSession, position_id: str) -> PositionResponse:
        position = await self._get(session, position_id)
        count = await self._active_count(session, position.id)
        return self._to_response(position, count)

    async def create_position(
        self, session: AsyncSession, data: PositionCreate
    ) -> PositionResponse:
        await self._ensure_code_free(session, data.code)
        position = Position(
            code=data.code,
            name=data.name,
            org_id=data.org_id,
            job_level=data.job_level,
            headcount=data.headcount,
            status=data.status,
        )
        session.add(position)
        await session.flush()
        _logger.info(f"岗位创建完成: {position.code} {position.name}")
        return self._to_response(position, 0)

    async def update_position(
        self, session: AsyncSession, position_id: str, data: PositionUpdate
    ) -> PositionResponse:
        position = await self._get(session, position_id)
        updates = data.model_dump(exclude_unset=True, exclude_none=True)
        if "code" in updates and updates["code"] != position.code:
            await self._ensure_code_free(session, updates["code"])
        for field, value in updates.items():
            setattr(position, field, value)
        await session.flush()
        count = await self._active_count(session, position.id)
        return self._to_response(position, count)

    async def delete_position(self, session: AsyncSession, position_id: str) -> None:
        """删除保护：在岗员工 > 0 不可删除，仅可停用。"""
        position = await self._get(session, position_id)
        count = await self._active_count(session, position.id)
        if count > 0:
            raise ConflictError(f"该岗位仍有 {count} 名在岗员工，不可删除，仅可停用")
        await session.delete(position)
        await session.flush()
        _logger.info(f"岗位删除: {position.code}")

    # ── 内部工具 ──

    async def _get(self, session: AsyncSession, position_id: str) -> Position:
        position = await session.get(Position, position_id)
        if not position:
            raise NotFoundError(f"岗位 {position_id} 不存在")
        return position

    async def _ensure_code_free(self, session: AsyncSession, code: str) -> None:
        result = await session.execute(
            select(Position).where(Position.code == code)
        )
        if result.scalar_one_or_none():
            raise ConflictError(f"岗位编码 {code} 已存在")

    async def _active_counts(
        self, session: AsyncSession, position_ids: list[str]
    ) -> dict[str, int]:
        """在岗人数批量实时统计（不含离职）。"""
        if not position_ids:
            return {}
        result = await session.execute(
            select(Employee.position_id, func.count())
            .where(
                Employee.position_id.in_(position_ids),
                Employee.status != "offboarded",
            )
            .group_by(Employee.position_id)
        )
        return {row[0]: row[1] for row in result.all()}

    async def _active_count(self, session: AsyncSession, position_id: str) -> int:
        counts = await self._active_counts(session, [position_id])
        return counts.get(position_id, 0)

    @staticmethod
    def _to_response(position: Position, active_count: int) -> PositionResponse:
        return PositionResponse(
            id=position.id,
            code=position.code,
            name=position.name,
            org_id=position.org_id,
            job_level=position.job_level,
            headcount=position.headcount,
            active_employee_count=active_count,
            status=position.status,
        )


position_service = PositionService()
