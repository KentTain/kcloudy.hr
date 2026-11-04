"""绩效域服务：考核周期状态机 + 目标整批提交（权重合计 100）+ 评级分布聚合

周期状态机单向推进 draft → active → scoring → calibrating → closed（非法跃迁 409），
仅 draft 可编辑/删除；目标按「员工 × 周期」整批提交（active 态），权重合计须恰好 100
（不足/超额均拒绝并提示缺口），单目标编辑复核合计；评级分布口径 calibrated_rating
优先回退 rating（附强制分布规则线）；close 时经 perf_review_service 收口写评估系数。
"""

from datetime import date
from decimal import Decimal

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.ctx import get_tenant_id
from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError

from hr.models import Employee, PerfCycle, PerfGoal, PerfReview

_logger = logger.bind(name=__name__)

_ACTIVE_EMPLOYEE_STATUSES = ("probation", "regular", "intern")

# 状态机单向推进表：action -> (允许源状态, 目标状态)
TRANSITIONS: dict[str, tuple[str, str]] = {
    "activate": ("draft", "active"),
    "scoring": ("active", "scoring"),
    "calibrating": ("scoring", "calibrating"),
    "close": ("calibrating", "closed"),
}

_RATINGS = ("S", "A", "B", "C", "D")

_FULL_WEIGHT = Decimal("100")


def _weight_gap_message(total: Decimal) -> str:
    gap = _FULL_WEIGHT - total
    if gap > 0:
        return f"目标权重合计 {total}，不足 100（尚缺 {gap}）"
    return f"目标权重合计 {total}，超出 100（超出 {-gap}）"


class PerfCycleService:
    """考核周期与绩效目标业务（状态推进需 hr:perf_cycle:write，写 iam 审计）"""

    # ── 周期 ──

    async def list_cycles(
        self,
        session: AsyncSession,
        *,
        status: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        conditions = []
        if status:
            conditions.append(PerfCycle.status == status)
        if date_from:
            conditions.append(PerfCycle.end_date >= date_from)
        if date_to:
            conditions.append(PerfCycle.start_date <= date_to)
        if keyword:
            conditions.append(PerfCycle.name.ilike(f"%{keyword}%"))

        total = (
            await session.execute(
                select(func.count(PerfCycle.id)).where(*conditions)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(PerfCycle)
                .where(*conditions)
                .order_by(PerfCycle.start_date.desc(), PerfCycle.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        goal_counts, review_counts = await self._cycle_stat_maps(
            session, [cycle.id for cycle in rows]
        )
        return {
            "total": total,
            "items": [
                self.to_response(
                    cycle,
                    goal_count=goal_counts.get(cycle.id, 0),
                    review_count=review_counts.get(cycle.id, 0),
                )
                for cycle in rows
            ],
        }

    async def get_cycle(self, session: AsyncSession, cycle_id: str) -> dict:
        cycle = await self._get_cycle(session, cycle_id)
        goal_counts, review_counts = await self._cycle_stat_maps(session, [cycle.id])
        return self.to_response(
            cycle,
            goal_count=goal_counts.get(cycle.id, 0),
            review_count=review_counts.get(cycle.id, 0),
        )

    async def create_cycle(
        self, session: AsyncSession, *, name: str, start_date: date, end_date: date
    ) -> PerfCycle:
        if end_date < start_date:
            raise BadRequestError("截止日期须不早于起始日期")
        existing = (
            await session.execute(
                select(PerfCycle).where(PerfCycle.name == name).limit(1)
            )
        ).scalar_one_or_none()
        if existing:
            raise ConflictError(f"周期名 {name} 已存在（租户内唯一）")
        cycle = PerfCycle(
            tenant_id=get_tenant_id(),
            name=name,
            start_date=start_date,
            end_date=end_date,
            status="draft",
        )
        session.add(cycle)
        await session.flush()
        return cycle

    async def update_cycle(
        self,
        session: AsyncSession,
        cycle_id: str,
        *,
        name: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> PerfCycle:
        cycle = await self._get_cycle(session, cycle_id)
        if cycle.status != "draft":
            raise ConflictError(f"周期状态为 {cycle.status}，仅草稿可编辑")
        if name is not None and name != cycle.name:
            existing = (
                await session.execute(
                    select(PerfCycle).where(PerfCycle.name == name).limit(1)
                )
            ).scalar_one_or_none()
            if existing:
                raise ConflictError(f"周期名 {name} 已存在（租户内唯一）")
            cycle.name = name
        if start_date is not None:
            cycle.start_date = start_date
        if end_date is not None:
            cycle.end_date = end_date
        if cycle.end_date < cycle.start_date:
            raise BadRequestError("截止日期须不早于起始日期")
        await session.flush()
        return cycle

    async def delete_cycle(self, session: AsyncSession, cycle_id: str) -> None:
        cycle = await self._get_cycle(session, cycle_id)
        if cycle.status != "draft":
            raise ConflictError(f"周期状态为 {cycle.status}，仅草稿可删除")
        await session.delete(cycle)
        await session.flush()

    async def transition(
        self, session: AsyncSession, cycle_id: str, *, action: str
    ) -> PerfCycle:
        """状态机单向推进（非法跃迁 409）；close 时收口写评估系数（校准评级映射，兜底 1.0）。"""
        if action not in TRANSITIONS:
            raise BadRequestError(f"未知状态动作: {action}")
        source, target = TRANSITIONS[action]
        cycle = await self._get_cycle(session, cycle_id)
        if cycle.status != source:
            raise ConflictError(
                f"周期状态为 {cycle.status}，仅 {source} 状态可执行 {action}"
            )
        cycle.status = target
        await session.flush()
        if action == "close":
            from hr.services.perf_review_service import perf_review_service

            await perf_review_service.finalize_cycle(session, cycle_id)
        _logger.info(f"考核周期状态推进 cycle={cycle_id} {source} -> {target}")
        return cycle

    async def distribution(self, session: AsyncSession, cycle_id: str) -> dict:
        """评级分布（S/A/B/C/D 人数+占比+强制分布规则线，全五级补零）。"""
        from hr.services.perf_review_service import perf_review_service

        await self._get_cycle(session, cycle_id)
        rating_expr = func.coalesce(PerfReview.calibrated_rating, PerfReview.rating)
        rows = (
            await session.execute(
                select(rating_expr, func.count(PerfReview.id))
                .where(PerfReview.cycle_id == cycle_id, rating_expr.is_not(None))
                .group_by(rating_expr)
            )
        ).all()
        counts = {rating: 0 for rating in _RATINGS}
        for rating, count in rows:
            if rating in counts:
                counts[rating] = int(count)
        total = sum(counts.values())
        setting = await perf_review_service.get_perf_setting(session)
        return {
            "cycle_id": cycle_id,
            "total": total,
            "ratings": {
                rating: {
                    "count": counts[rating],
                    "percent": round(counts[rating] * 100 / total, 1) if total else 0.0,
                }
                for rating in _RATINGS
            },
            "rules": setting["distribution_rules"],
        }

    # ── 目标 ──

    async def list_goals(
        self,
        session: AsyncSession,
        *,
        cycle_id: str | None = None,
        employee_id: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        conditions = []
        if cycle_id:
            conditions.append(PerfGoal.cycle_id == cycle_id)
        if employee_id:
            conditions.append(PerfGoal.employee_id == employee_id)
        if status:
            conditions.append(PerfGoal.status == status)

        total = (
            await session.execute(
                select(func.count(PerfGoal.id))
                .join(Employee, PerfGoal.employee_id == Employee.id)
                .where(*conditions)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(PerfGoal, Employee)
                .join(Employee, PerfGoal.employee_id == Employee.id)
                .where(*conditions)
                .order_by(PerfGoal.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return {
            "total": total,
            "items": [self.goal_to_response(goal, employee) for goal, employee in rows],
        }

    async def submit_goals(
        self, session: AsyncSession, *, cycle_id: str, employee_id: str, goals: list[dict]
    ) -> list[PerfGoal]:
        """目标整批提交：active 态，权重合计须恰好 100；同员工同周期整体替换未完成目标。"""
        cycle = await self._get_cycle(session, cycle_id)
        if cycle.status != "active":
            raise ConflictError(
                f"周期状态为 {cycle.status}，仅进行中（active）可制定目标"
            )
        if not goals:
            raise BadRequestError("目标列表不可为空")
        employee = await session.get(Employee, employee_id)
        if not employee:
            raise NotFoundError(f"员工 {employee_id} 不存在")
        if employee.status not in _ACTIVE_EMPLOYEE_STATUSES:
            raise ConflictError("仅在职员工可制定目标")

        total = Decimal("0")
        for item in goals:
            weight = Decimal(str(item.get("weight") or 0))
            if weight <= 0:
                raise BadRequestError("目标权重须大于 0")
            total += weight
        if total != _FULL_WEIGHT:
            raise BadRequestError(_weight_gap_message(total))

        codes = [item["code"] for item in goals]
        existing = (
            await session.execute(
                select(PerfGoal).where(PerfGoal.code.in_(codes))
            )
        ).scalars().all()
        if existing:
            raise BadRequestError(
                f"目标编码已存在: {', '.join(sorted({goal.code for goal in existing}))}"
            )

        olds = (
            await session.execute(
                select(PerfGoal).where(
                    PerfGoal.cycle_id == cycle_id,
                    PerfGoal.employee_id == employee_id,
                    PerfGoal.status == "open",
                )
            )
        ).scalars().all()
        for old in olds:
            await session.delete(old)

        created: list[PerfGoal] = []
        for item in goals:
            goal = PerfGoal(
                tenant_id=get_tenant_id(),
                cycle_id=cycle_id,
                employee_id=employee_id,
                code=item["code"],
                name=item["name"],
                weight=Decimal(str(item["weight"])),
                target_value=item.get("target_value"),
                progress=0,
                status="open",
            )
            session.add(goal)
            created.append(goal)
        await session.flush()
        _logger.info(
            f"目标整批提交 cycle={cycle_id} employee={employee_id} count={len(created)}"
        )
        return created

    async def update_goal(
        self,
        session: AsyncSession,
        goal_id: str,
        *,
        name: str | None = None,
        weight: Decimal | None = None,
        target_value: str | None = None,
    ) -> PerfGoal:
        """单目标编辑（active 态未完成）；改权重后全组合计须仍为 100。"""
        goal = await self._get_goal(session, goal_id)
        cycle = await self._get_cycle(session, goal.cycle_id)
        if cycle.status != "active":
            raise ConflictError(
                f"周期状态为 {cycle.status}，仅进行中（active）可编辑目标"
            )
        if goal.status != "open":
            raise ConflictError("已完成目标不可编辑")
        if weight is not None:
            new_weight = Decimal(str(weight))
            if new_weight <= 0:
                raise BadRequestError("目标权重须大于 0")
            if new_weight != goal.weight:
                others = (
                    await session.execute(
                        select(func.coalesce(func.sum(PerfGoal.weight), 0)).where(
                            PerfGoal.cycle_id == goal.cycle_id,
                            PerfGoal.employee_id == goal.employee_id,
                            PerfGoal.id != goal.id,
                        )
                    )
                ).scalar_one()
                total = Decimal(str(others)) + new_weight
                if total != _FULL_WEIGHT:
                    raise BadRequestError(_weight_gap_message(total))
                goal.weight = new_weight
        if name is not None:
            goal.name = name
        if target_value is not None:
            goal.target_value = target_value
        await session.flush()
        return goal

    async def update_goal_progress(
        self,
        session: AsyncSession,
        goal_id: str,
        *,
        progress: int,
        actual_value: str | None = None,
    ) -> PerfGoal:
        """进度与实际值更新（active/scoring 态）；进度达 100 自动置 completed。"""
        goal = await self._get_goal(session, goal_id)
        cycle = await self._get_cycle(session, goal.cycle_id)
        if cycle.status not in ("active", "scoring"):
            raise ConflictError(
                f"周期状态为 {cycle.status}，仅进行中/评分中可更新目标进度"
            )
        if not 0 <= progress <= 100:
            raise BadRequestError("进度须在 0-100 之间")
        goal.progress = progress
        if actual_value is not None:
            goal.actual_value = actual_value
        if progress >= 100:
            goal.status = "completed"
        await session.flush()
        return goal

    async def delete_goal(self, session: AsyncSession, goal_id: str) -> None:
        goal = await self._get_goal(session, goal_id)
        cycle = await self._get_cycle(session, goal.cycle_id)
        if cycle.status != "active":
            raise ConflictError(
                f"周期状态为 {cycle.status}，仅进行中（active）可删除目标"
            )
        if goal.status != "open":
            raise ConflictError("已完成目标不可删除")
        await session.delete(goal)
        await session.flush()

    # ── 内部 ──

    async def _get_cycle(self, session: AsyncSession, cycle_id: str) -> PerfCycle:
        cycle = await session.get(PerfCycle, cycle_id)
        if not cycle:
            raise NotFoundError(f"考核周期 {cycle_id} 不存在")
        return cycle

    async def _get_goal(self, session: AsyncSession, goal_id: str) -> PerfGoal:
        goal = await session.get(PerfGoal, goal_id)
        if not goal:
            raise NotFoundError(f"绩效目标 {goal_id} 不存在")
        return goal

    async def _cycle_stat_maps(
        self, session: AsyncSession, cycle_ids: list[str]
    ) -> tuple[dict, dict]:
        """周期目标数/评估数统计（两条分组聚合，避免逐行 N+1）。"""
        goal_counts: dict = {}
        review_counts: dict = {}
        if not cycle_ids:
            return goal_counts, review_counts
        goal_rows = (
            await session.execute(
                select(PerfGoal.cycle_id, func.count(PerfGoal.id))
                .where(PerfGoal.cycle_id.in_(cycle_ids))
                .group_by(PerfGoal.cycle_id)
            )
        ).all()
        goal_counts = {cycle_id: int(count) for cycle_id, count in goal_rows}
        review_rows = (
            await session.execute(
                select(PerfReview.cycle_id, func.count(PerfReview.id))
                .where(PerfReview.cycle_id.in_(cycle_ids))
                .group_by(PerfReview.cycle_id)
            )
        ).all()
        review_counts = {cycle_id: int(count) for cycle_id, count in review_rows}
        return goal_counts, review_counts

    def to_response(
        self,
        cycle: PerfCycle,
        *,
        goal_count: int = 0,
        review_count: int = 0,
    ) -> dict:
        return {
            "id": str(cycle.id),
            "name": cycle.name,
            "start_date": cycle.start_date,
            "end_date": cycle.end_date,
            "status": cycle.status,
            "goal_count": goal_count,
            "review_count": review_count,
            "created_at": cycle.created_at,
            "updated_at": cycle.updated_at,
        }

    def goal_to_response(self, goal: PerfGoal, employee: Employee | None = None) -> dict:
        return {
            "id": str(goal.id),
            "cycle_id": goal.cycle_id,
            "employee_id": goal.employee_id,
            "employee_no": employee.employee_no if employee else None,
            "employee_name": employee.name if employee else None,
            "code": goal.code,
            "name": goal.name,
            "weight": goal.weight,
            "target_value": goal.target_value,
            "actual_value": goal.actual_value,
            "progress": goal.progress,
            "status": goal.status,
            "created_at": goal.created_at,
        }


perf_cycle_service = PerfCycleService()
