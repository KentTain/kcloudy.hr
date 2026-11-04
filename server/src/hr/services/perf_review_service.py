"""绩效评估服务：批量发起（去重）+ 评分（scoring 态）+ 校准（calibrating 态留痕）+ 收口写系数

评估（被评人 × 周期唯一）状态 pending → submitted（评分）→ calibrated（校准）；
评分仅周期 scoring 态，校准仅周期 calibrating 态且评估已提交初评（意见必填，
留痕校准人/前后评级/时间）；周期收口（close）时按 calibrated_rating 优先回退
rating 映射写 coefficient，映射读租户配置 hr_perf_setting.rating_coefficients，
缺省兜底 1.0。分布规则线（强制分布参考）同源 hr_perf_setting.distribution_rules。
"""

from datetime import UTC, datetime
from decimal import Decimal

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from framework.common.ctx import get_tenant_id
from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError

from hr.models import Employee, PerfCycle, PerfGoal, PerfReview

_logger = logger.bind(name=__name__)

_RATINGS = ("S", "A", "B", "C", "D")

_SETTING_CODE = "hr_perf_setting"

# 评级 → 绩效系数（租户未配置 hr_perf_setting.rating_coefficients 时的兜底映射）
_DEFAULT_RATING_COEFFICIENTS: dict[str, str] = {
    "S": "1.5",
    "A": "1.2",
    "B": "1.0",
    "C": "0.8",
    "D": "0.5",
}

_FALLBACK_COEFFICIENT = Decimal("1.0")

# 强制分布规则线（占比上限 %，租户未配置时兜底；仅校准参考不强制拦截）
_DEFAULT_DISTRIBUTION_RULES: dict[str, float] = {"S": 10.0, "A": 20.0}

_ACTIVE_EMPLOYEE_STATUSES = ("probation", "regular", "intern")


class PerfReviewService:
    """绩效评估业务（评分需 hr:perf_review:write，校准需 hr:perf:calibrate，写 iam 审计）"""

    # ── 配置 ──

    async def get_perf_setting(self, session: AsyncSession) -> dict:
        """读租户绩效设置 hr_perf_setting，缺省回退内置映射。"""
        from framework.clients.iam_client import get_iam_client

        values = await get_iam_client().get_system_setting(
            session, get_tenant_id(), _SETTING_CODE
        )
        raw_coefficients = (values or {}).get("rating_coefficients")
        coefficients: dict[str, Decimal] = {}
        if isinstance(raw_coefficients, dict):
            for rating, value in raw_coefficients.items():
                if rating in _RATINGS:
                    try:
                        coefficients[rating] = Decimal(str(value))
                    except Exception:  # noqa: BLE001 - 配置脏值按缺省兜底
                        continue
        raw_rules = (values or {}).get("distribution_rules")
        rules: dict[str, float] = dict(_DEFAULT_DISTRIBUTION_RULES)
        if isinstance(raw_rules, dict):
            for rating, value in raw_rules.items():
                if rating in _RATINGS:
                    try:
                        rules[rating] = float(value)
                    except (TypeError, ValueError):
                        continue
        return {
            "rating_coefficients": coefficients,
            "distribution_rules": rules,
        }

    def resolve_coefficient(
        self, coefficients: dict[str, Decimal], rating: str | None
    ) -> Decimal:
        """评级 → 系数：配置映射优先，未配置档位回退内置映射，评级为空兜底 1.0。"""
        if not rating:
            return _FALLBACK_COEFFICIENT
        if rating in coefficients:
            return coefficients[rating]
        if rating in _DEFAULT_RATING_COEFFICIENTS:
            return Decimal(_DEFAULT_RATING_COEFFICIENTS[rating])
        return _FALLBACK_COEFFICIENT

    # ── 评估 ──

    async def list_reviews(
        self,
        session: AsyncSession,
        *,
        cycle_id: str | None = None,
        status: str | None = None,
        reviewer_employee_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        Reviewer = aliased(Employee)
        conditions = []
        if cycle_id:
            conditions.append(PerfReview.cycle_id == cycle_id)
        if status:
            conditions.append(PerfReview.status == status)
        if reviewer_employee_id:
            conditions.append(PerfReview.reviewer_employee_id == reviewer_employee_id)

        total = (
            await session.execute(select(func.count(PerfReview.id)).where(*conditions))
        ).scalar_one()
        rows = (
            await session.execute(
                select(PerfReview, Employee, Reviewer, PerfCycle)
                .join(Employee, PerfReview.employee_id == Employee.id)
                .join(Reviewer, PerfReview.reviewer_employee_id == Reviewer.id)
                .join(PerfCycle, PerfReview.cycle_id == PerfCycle.id)
                .where(*conditions)
                .order_by(PerfReview.created_at.desc(), PerfReview.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        review_rows = [row[0] for row in rows]
        goal_stats = await self._goal_stat_map(
            session, cycle_id, [review.employee_id for review in review_rows]
        )
        return {
            "total": total,
            "items": [
                self.to_response(
                    review,
                    employee=employee,
                    reviewer=reviewer,
                    cycle_status=cycle.status,
                    goal_stats=goal_stats.get(review.employee_id),
                )
                for review, employee, reviewer, cycle in rows
            ],
        }

    async def create_reviews(
        self, session: AsyncSession, *, cycle_id: str, items: list[dict]
    ) -> dict:
        """批量发起评估（scoring 态）：周期 × 被评人唯一，已存在的跳过。

        评估人由发起人显式指定（员工模型无直属上级字段，整批可统一指定）。
        """
        cycle = await session.get(PerfCycle, cycle_id)
        if not cycle:
            raise NotFoundError(f"考核周期 {cycle_id} 不存在")
        if cycle.status != "scoring":
            raise ConflictError(
                f"周期状态为 {cycle.status}，仅评分中（scoring）可发起评估"
            )
        if not items:
            raise BadRequestError("被评人清单不可为空")

        employee_ids = {item["employee_id"] for item in items}
        for item in items:
            if not item.get("reviewer_employee_id"):
                raise BadRequestError("评估人不可为空")

        employees = (
            await session.execute(select(Employee).where(Employee.id.in_(employee_ids)))
        ).scalars().all()
        employee_map = {str(employee.id): employee for employee in employees}
        missing = employee_ids - set(employee_map)
        if missing:
            raise NotFoundError(f"员工不存在: {', '.join(sorted(missing))}")
        inactive = [
            employee.name
            for employee in employees
            if employee.status not in _ACTIVE_EMPLOYEE_STATUSES
        ]
        if inactive:
            raise ConflictError(f"仅在职员工可发起评估: {', '.join(inactive)}")

        existing = (
            await session.execute(
                select(PerfReview.employee_id).where(
                    PerfReview.cycle_id == cycle_id,
                    PerfReview.employee_id.in_(employee_ids),
                )
            )
        ).scalars().all()
        existing_ids = {str(employee_id) for employee_id in existing}

        created = 0
        skipped = 0
        for item in items:
            employee_id = item["employee_id"]
            if employee_id in existing_ids:
                skipped += 1
                continue
            session.add(
                PerfReview(
                    tenant_id=get_tenant_id(),
                    cycle_id=cycle_id,
                    employee_id=employee_id,
                    reviewer_employee_id=item["reviewer_employee_id"],
                    status="pending",
                )
            )
            created += 1
        await session.flush()
        _logger.info(
            f"批量发起评估 cycle={cycle_id} created={created} skipped={skipped}"
        )
        return {"cycle_id": cycle_id, "created": created, "skipped": skipped}

    async def submit_score(
        self,
        session: AsyncSession,
        review_id: str,
        *,
        score: Decimal,
        rating: str,
        self_score: Decimal | None = None,
    ) -> PerfReview:
        """提交评分（scoring 态）：得分+初评评级；已提交可覆盖重提，校准后锁定。"""
        review = await self._get_review(session, review_id)
        if review.status == "calibrated":
            raise ConflictError("评估已校准，评分不可再修改")
        cycle = await session.get(PerfCycle, review.cycle_id)
        if not cycle or cycle.status != "scoring":
            raise ConflictError(
                f"周期状态为 {getattr(cycle, 'status', None)}，仅评分中（scoring）可提交评分"
            )
        if rating not in _RATINGS:
            raise BadRequestError(f"评级须为 {'/'.join(_RATINGS)}")
        review.score = Decimal(str(score))
        review.rating = rating
        if self_score is not None:
            review.self_score = Decimal(str(self_score))
        review.status = "submitted"
        await session.flush()
        _logger.info(f"评估评分 review={review_id} score={score} rating={rating}")
        return review

    async def calibrate(
        self,
        session: AsyncSession,
        review_id: str,
        *,
        rating: str,
        comment: str,
        operator_user_id: str,
    ) -> PerfReview:
        """校准评级（calibrating 态 + 已提交初评）：意见必填，留痕操作人/前后评级/时间。"""
        review = await self._get_review(session, review_id)
        if rating not in _RATINGS:
            raise BadRequestError(f"评级须为 {'/'.join(_RATINGS)}")
        if not comment or not comment.strip():
            raise BadRequestError("校准意见必填")
        cycle = await session.get(PerfCycle, review.cycle_id)
        if not cycle or cycle.status != "calibrating":
            raise ConflictError(
                f"周期状态为 {getattr(cycle, 'status', None)}，仅校准中（calibrating）可校准评级"
            )
        if review.status == "pending" or not review.rating:
            raise ConflictError("评估尚未提交初评，不可校准")
        review.calibrated_rating = rating
        review.calibrated_by_user_id = operator_user_id
        review.calibration_comment = comment.strip()
        review.calibrated_at = datetime.now(UTC)
        review.status = "calibrated"
        await session.flush()
        _logger.info(
            f"评估校准 review={review_id} {review.rating} -> {rating} by={operator_user_id}"
        )
        return review

    async def finalize_cycle(self, session: AsyncSession, cycle_id: str) -> int:
        """周期收口写系数：calibrated_rating 优先回退 rating，映射缺省兜底 1.0。"""
        reviews = (
            await session.execute(
                select(PerfReview).where(PerfReview.cycle_id == cycle_id)
            )
        ).scalars().all()
        if not reviews:
            return 0
        setting = await self.get_perf_setting(session)
        coefficients = setting["rating_coefficients"]
        for review in reviews:
            review.coefficient = self.resolve_coefficient(
                coefficients, review.calibrated_rating or review.rating
            )
        await session.flush()
        _logger.info(f"周期收口写系数 cycle={cycle_id} count={len(reviews)}")
        return len(reviews)

    # ── 内部 ──

    async def _get_review(self, session: AsyncSession, review_id: str) -> PerfReview:
        review = await session.get(PerfReview, review_id)
        if not review:
            raise NotFoundError(f"绩效评估 {review_id} 不存在")
        return review

    async def _goal_stat_map(
        self,
        session: AsyncSession,
        cycle_id: str | None,
        employee_ids: list[str],
    ) -> dict[str, tuple[int, Decimal]]:
        """当页被评人的目标数与加权进度（sum(weight×progress)/100，一次分组聚合）。"""
        if not cycle_id or not employee_ids:
            return {}
        rows = (
            await session.execute(
                select(
                    PerfGoal.employee_id,
                    func.count(PerfGoal.id),
                    func.coalesce(func.sum(PerfGoal.weight * PerfGoal.progress), 0),
                )
                .where(
                    PerfGoal.cycle_id == cycle_id,
                    PerfGoal.employee_id.in_(employee_ids),
                )
                .group_by(PerfGoal.employee_id)
            )
        ).all()
        return {
            str(employee_id): (int(count), Decimal(str(weighted_sum)))
            for employee_id, count, weighted_sum in rows
        }

    def to_response(
        self,
        review: PerfReview,
        *,
        employee: Employee | None = None,
        reviewer: Employee | None = None,
        cycle_status: str | None = None,
        goal_stats: tuple[int, Decimal] | None = None,
    ) -> dict:
        count, weighted = goal_stats or (0, Decimal("0"))
        return {
            "id": str(review.id),
            "cycle_id": review.cycle_id,
            "cycle_status": cycle_status,
            "employee_id": review.employee_id,
            "employee_no": employee.employee_no if employee else None,
            "employee_name": employee.name if employee else None,
            "reviewer_employee_id": review.reviewer_employee_id,
            "reviewer_name": reviewer.name if reviewer else None,
            "goal_count": count,
            "weighted_progress": round(float(weighted) / 100, 1),
            "self_score": review.self_score,
            "score": review.score,
            "rating": review.rating,
            "calibrated_rating": review.calibrated_rating,
            "calibration_comment": review.calibration_comment,
            "calibrated_at": review.calibrated_at,
            "coefficient": review.coefficient,
            "status": review.status,
            "created_at": review.created_at,
        }


perf_review_service = PerfReviewService()
