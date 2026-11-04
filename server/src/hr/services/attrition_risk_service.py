"""离职风险评分服务（规则加权，实时计算不落库）

五因子口径（内置常量，不配置化）：
- 薪酬分位低于职级薪带下限 +30；
- 近 90 天考勤异常（迟到/早退/早晚/缺勤）≥3 次 +20；
- 最近 closed 周期评级 S/A 且薪酬低于带宽中位 +20；
- 司龄 1-3 年（波动期）+15；
- 近 180 天无任何异动且司龄 ≥2 年 +15。

风险等级：score ≥60 高 / 40-59 中 / <40 低；仅返回得分 > 0 的在编员工（按分倒序）。
无薪酬权限查看者（include_comp=False）剔除全部薪酬因子，口径与 00.通用设计一致。
"""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hr.models import (
    AttendanceRecord,
    Employee,
    EmployeeChange,
    EmployeeSalaryPackage,
    PerfCycle,
    PerfReview,
    SalaryBand,
)
from hr.schemas.report import AttritionRiskItem, AttritionRiskResponse
from hr.services.employee_service import employee_service

SCORE_LOW_COMP = 30
SCORE_ATTENDANCE = 20
SCORE_PERF_COMP = 20
SCORE_TENURE = 15
SCORE_STAGNANT = 15
HIGH_THRESHOLD = 60
MID_THRESHOLD = 40

_ATTENDANCE_ABNORMAL = ("late", "early_leave", "late_early", "absent")
_TOP_RATINGS = ("S", "A")
_ABNORMAL_THRESHOLD = 3
_TENURE_MIN_YEARS = 1
_TENURE_MAX_YEARS = 3
_STAGNANT_MIN_YEARS = 2


def _risk_level(score: int) -> str:
    if score >= HIGH_THRESHOLD:
        return "high"
    if score >= MID_THRESHOLD:
        return "mid"
    return "low"


class AttritionRiskService:
    """离职风险名单（规则加权评分，随查询实时计算）"""

    async def get_risk_list(
        self,
        session: AsyncSession,
        *,
        org_id: str | None = None,
        limit: int = 20,
        include_comp: bool = True,
    ) -> AttritionRiskResponse:
        today = date.today()
        conditions = [Employee.status.in_(("probation", "regular"))]
        if org_id:
            org_ids = await employee_service.expand_org_ids(session, org_id)
            conditions.append(Employee.org_id.in_(org_ids))
        employees = (
            await session.execute(
                select(
                    Employee.id,
                    Employee.employee_no,
                    Employee.name,
                    Employee.org_id,
                    Employee.job_level,
                    Employee.hire_date,
                ).where(*conditions)
            )
        ).all()
        if not employees:
            return AttritionRiskResponse(total=0, items=[])

        salary_totals: dict[str, float] = {}
        bands: dict[str, tuple[float, float, float]] = {}
        if include_comp:
            totals = (
                await session.execute(
                    select(
                        EmployeeSalaryPackage.employee_id,
                        func.sum(EmployeeSalaryPackage.amount),
                    )
                    .where(
                        EmployeeSalaryPackage.effective_from <= today,
                        (EmployeeSalaryPackage.effective_to.is_(None))
                        | (EmployeeSalaryPackage.effective_to >= today),
                    )
                    .group_by(EmployeeSalaryPackage.employee_id)
                )
            ).all()
            salary_totals = {employee_id: float(amount) for employee_id, amount in totals}
            band_rows = (
                await session.execute(
                    select(
                        SalaryBand.job_level,
                        SalaryBand.min_salary,
                        SalaryBand.mid_salary,
                        SalaryBand.max_salary,
                    ).where(
                        SalaryBand.effective_to.is_(None),
                        SalaryBand.effective_from <= today,
                    )
                )
            ).all()
            bands = {
                job_level: (float(low), float(mid), float(high))
                for job_level, low, mid, high in band_rows
            }

        since_90 = today - timedelta(days=90)
        abnormal_counts = dict(
            (
                await session.execute(
                    select(AttendanceRecord.employee_id, func.count())
                    .where(
                        AttendanceRecord.work_date >= since_90,
                        AttendanceRecord.status.in_(_ATTENDANCE_ABNORMAL),
                    )
                    .group_by(AttendanceRecord.employee_id)
                )
            ).all()
        )

        latest_closed = (
            await session.execute(
                select(PerfCycle.id)
                .where(PerfCycle.status == "closed")
                .order_by(PerfCycle.end_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        top_rated: set[str] = set()
        if latest_closed:
            perf_rows = (
                await session.execute(
                    select(
                        PerfReview.employee_id,
                        PerfReview.calibrated_rating,
                        PerfReview.rating,
                    ).where(PerfReview.cycle_id == latest_closed)
                )
            ).all()
            for employee_id, calibrated, rating in perf_rows:
                if (calibrated or rating) in _TOP_RATINGS:
                    top_rated.add(employee_id)

        since_180 = today - timedelta(days=180)
        changed_rows = (
            await session.execute(
                select(EmployeeChange.employee_id).where(
                    EmployeeChange.effective_date >= since_180
                )
            )
        ).scalars().all()
        changed = set(changed_rows)

        items: list[AttritionRiskItem] = []
        for row_id, employee_no, name, org, job_level, hire_date in employees:
            employee_id = str(row_id)
            score = 0
            factors: list[str] = []
            total_salary = salary_totals.get(employee_id)
            band = bands.get(job_level or "")
            if total_salary is not None and band is not None:
                if total_salary < band[0]:
                    score += SCORE_LOW_COMP
                    factors.append("薪酬低于职级薪带下限")
                if employee_id in top_rated and total_salary < band[1]:
                    score += SCORE_PERF_COMP
                    factors.append("绩效优（S/A）但薪酬低于带宽中位")
            if abnormal_counts.get(employee_id, 0) >= _ABNORMAL_THRESHOLD:
                score += SCORE_ATTENDANCE
                factors.append("近90天考勤异常≥3次")
            tenure_years = (
                (today - hire_date).days / 365.25 if hire_date else 0.0
            )
            if _TENURE_MIN_YEARS <= tenure_years < _TENURE_MAX_YEARS:
                score += SCORE_TENURE
                factors.append("司龄处于1-3年波动期")
            if tenure_years >= _STAGNANT_MIN_YEARS and employee_id not in changed:
                score += SCORE_STAGNANT
                factors.append("近180天无异动且司龄≥2年")
            if score > 0:
                items.append(
                    AttritionRiskItem(
                        employee_id=employee_id,
                        employee_no=employee_no,
                        name=name,
                        org_id=str(org) if org else None,
                        score=score,
                        level=_risk_level(score),
                        factors=factors,
                    )
                )
        items.sort(key=lambda item: -item.score)
        return AttritionRiskResponse(total=len(employees), items=items[:limit])


attrition_risk_service = AttritionRiskService()
