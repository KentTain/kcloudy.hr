"""报表服务：人事仪表盘 / 离职率序列 / 招聘漏斗与渠道转化 / 薪酬分布（脱敏）/ 绩效分布

口径约定：
- 在编 = status ∈ {probation, regular}（与员工管理统计卡一致）；
- 在编趋势/离职率序列由员工主档生命周期（hire_date/offboard_date）回算按月序列；
- 漏斗按投递申请计（与候选人页三段漏斗统计卡同源，stage 顺序复用 requisition_service）；
- 薪酬分布 = 当期生效定薪按员工月度总额聚合，仅 min/mid/max 脱敏口径；
- 绩效报表 = closed 周期评级分布（calibrated_rating 优先回退 rating）+ 周期均分趋势；
- 真日期区间：overview/turnover 统一接受 date_from/date_to（按区间取整月序列），
  months 参数兼容保留（无区间时按月数回溯）；org_id 为组织子树下钻口径，下钻查询不走快照；
- 招聘域快照按月度桶存储（funnel/channels 按月聚合），区间查询逐桶聚合；
- 核心指标与序列走 Redis 快照缓存（报表快照任务每日刷新四域：personnel/recruiting/
  compensation/performance），miss 回源实时计算。
"""

import json
from datetime import date, datetime, time, timedelta

from framework.cache.redis_util import RedisUtil
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hr.models import (
    Candidate,
    CandidateApplication,
    Employee,
    EmployeeSalaryPackage,
    JobRequisition,
    PerfCycle,
    PerfReview,
)
from hr.schemas.report import (
    ChannelStageCount,
    CompDistItem,
    CompDistResponse,
    CyclePerformanceItem,
    FunnelStageCount,
    MetricRef,
    OrgDistributionItem,
    PerformanceReportResponse,
    RecruitingReportResponse,
    OverviewResponse,
    TrendPoint,
    TurnoverPoint,
    TurnoverResponse,
)
from hr.services.employee_service import employee_service
from hr.services.requisition_service import requisition_service

SNAPSHOT_KEY_PREFIX = "hr:report:snapshot:"
SNAPSHOT_TTL_SECONDS = 25 * 3600
SNAPSHOT_MONTHS = 12
_ACTIVE_STATUSES = ("probation", "regular")

# 内置指标口径（ontology 注册同源：hr/services/ontology_provision_service._METRICS；
# ontology 有定义时响应 ref 读 ontology，缺席/异常回退此处）
_BUILTIN_METRICS: dict[str, tuple[str, str]] = {
    "attrition_rate": (
        "离职率",
        "当月离职人数 / 当月平均在编人数（百分数），按员工生命周期月末口径回算",
    ),
    "headcount_gap": (
        "编制缺口",
        "在编人数统计（active = probation/regular），与组织编制基准的缺口汇总",
    ),
    "perf_rating_distribution": (
        "绩效评级分布",
        "已收口周期内员工评级分布（校准评级优先），总人数按评估记录行数累计",
    ),
}


def _month_end(month_first: date) -> date:
    if month_first.month == 12:
        return month_first.replace(day=31)
    return month_first.replace(
        month=month_first.month + 1, day=1
    ) - timedelta(days=1)


def _month_label(value: date) -> str:
    return value.strftime("%Y-%m")


def _day_start(value: date) -> datetime:
    return datetime.combine(value, time.min)


def _day_end(value: date) -> datetime:
    return datetime.combine(value + timedelta(days=1), time.min)


def build_month_range(months: int, *, today: date | None = None) -> list[date]:
    """近 months 个月的月初序列（含当月，升序）。"""
    anchor = (today or date.today()).replace(day=1)
    result = []
    year, month = anchor.year, anchor.month
    for _ in range(months):
        result.append(date(year, month, 1))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    result.reverse()
    return result


def build_month_range_from_interval(date_from: date, date_to: date) -> list[date]:
    """与 [date_from, date_to] 相交的整月月初序列（升序）。"""
    start = date_from.replace(day=1)
    result = []
    year, month = start.year, start.month
    while True:
        first = date(year, month, 1)
        if first > date_to:
            break
        result.append(first)
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return result


def resolve_month_range(
    date_from: date | None, date_to: date | None, months: int
) -> list[date]:
    """真日期区间优先（整月序列），否则 months 回溯（兼容参数）。"""
    if date_from and date_to:
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        return build_month_range_from_interval(date_from, date_to)
    return build_month_range(months or 6)


def _slice_series(
    raw_items: list[dict], months_range: list[date]
) -> list[dict] | None:
    """快照切片：区间完整落在快照窗口内返回按月切片，否则 None（回源实时）。"""
    if not raw_items:
        return None
    labels = [item["month"] for item in raw_items]
    if labels[0] > _month_label(months_range[0]):
        return None
    if labels[-1] < _month_label(months_range[-1]):
        return None
    wanted = {_month_label(value) for value in months_range}
    return [item for item in raw_items if item["month"] in wanted]


def compute_headcount_trend(
    lifecycles: list[tuple[date, date | None]], months_range: list[date]
) -> list[TrendPoint]:
    """主档生命周期（hire_date, offboard_date）→ 按月月末在编序列。"""
    points = []
    for month_first in months_range:
        month_last = _month_end(month_first)
        count = sum(
            1
            for hire_date, offboard_date in lifecycles
            if hire_date <= month_last
            and (offboard_date is None or offboard_date > month_last)
        )
        points.append(TrendPoint(month=_month_label(month_first), count=count))
    return points


def compute_turnover(
    lifecycles: list[tuple[date, date | None]], months_range: list[date]
) -> list[TurnoverPoint]:
    """离职率序列：当月离职人数 / 当月平均在编（月初+月末均值）。"""
    points = []
    for month_first in months_range:
        month_last = _month_end(month_first)
        prev_month_last = month_first - timedelta(days=1)
        headcount_start = sum(
            1
            for hire_date, offboard_date in lifecycles
            if hire_date <= prev_month_last
            and (offboard_date is None or offboard_date > prev_month_last)
        )
        headcount_end = sum(
            1
            for hire_date, offboard_date in lifecycles
            if hire_date <= month_last
            and (offboard_date is None or offboard_date > month_last)
        )
        avg_headcount = round((headcount_start + headcount_end) / 2)
        offboarded = sum(
            1
            for _, offboard_date in lifecycles
            if offboard_date is not None
            and month_first <= offboard_date <= month_last
        )
        rate = (
            round(offboarded * 100 / avg_headcount, 2) if avg_headcount else None
        )
        points.append(
            TurnoverPoint(
                month=_month_label(month_first),
                offboarded=offboarded,
                avg_headcount=avg_headcount,
                rate=rate,
            )
        )
    return points


class ReportService:
    """报表业务（快照缓存优先 + miss 回源实时；组织下钻不走快照）"""

    async def _metric_ref(self, session: AsyncSession, metric: str) -> MetricRef:
        """指标口径引用：优先读 ontology metric 定义，缺席/异常回退内置说明。"""
        display, description = _BUILTIN_METRICS[metric]
        try:
            from framework.clients.ontology_client import get_ontology_client
            from framework.tenant.context import TenantContext

            entity = await get_ontology_client().entity_get_by_fqn(
                session,
                tenant_id=TenantContext.get_tenant_id(),
                spec_key="metric",
                fqn=metric,
            )
            if entity is not None:
                return MetricRef(
                    metric=metric,
                    display_name=str(entity.get("displayName") or display),
                    description=str(entity.get("description") or description),
                    source="ontology",
                )
        except Exception:  # noqa: BLE001 ontology 缺席/查询失败回退内置
            pass
        return MetricRef(
            metric=metric,
            display_name=display,
            description=description,
            source="builtin",
        )

    # ── 人事仪表盘 ──

    async def get_overview(
        self,
        session: AsyncSession,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        org_id: str | None = None,
        months: int = 6,
    ) -> OverviewResponse:
        months_range = resolve_month_range(date_from, date_to, months)
        org_ids = await self._resolve_org_ids(session, org_id)
        cards = await employee_service.get_stats(session, org_id=org_id)
        trend = await self._personnel_series(
            session, months_range, org_ids=org_ids, field="headcount_trend"
        )
        conditions = [Employee.status.in_(_ACTIVE_STATUSES)]
        if org_ids is not None:
            conditions.append(Employee.org_id.in_(org_ids))
        org_rows = (
            await session.execute(
                select(Employee.org_id, func.count(Employee.id))
                .where(*conditions)
                .group_by(Employee.org_id)
            )
        ).all()
        org_distribution = sorted(
            (
                OrgDistributionItem(org_id=str(org) if org else None, count=count)
                for org, count in org_rows
            ),
            key=lambda item: -item.count,
        )
        return OverviewResponse(
            cards=cards,
            headcount_trend=[TrendPoint(**item) for item in trend],
            org_distribution=org_distribution,
            metric_ref=await self._metric_ref(session, "headcount_gap"),
        )

    async def get_turnover(
        self,
        session: AsyncSession,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        org_id: str | None = None,
        months: int = 6,
    ) -> TurnoverResponse:
        months_range = resolve_month_range(date_from, date_to, months)
        org_ids = await self._resolve_org_ids(session, org_id)
        points = await self._personnel_series(
            session, months_range, org_ids=org_ids, field="turnover"
        )
        return TurnoverResponse(
            points=[TurnoverPoint(**item) for item in points],
            metric_ref=await self._metric_ref(session, "attrition_rate"),
        )

    async def _get_snapshot(self, session: AsyncSession) -> dict:
        """快照缓存（固定近 12 月趋势+离职率序列）优先，miss 实时计算并回填。"""
        cached = await self._read_snapshot("personnel")
        if cached is not None and "headcount_trend" in cached and "turnover" in cached:
            return cached
        lifecycles = await self._load_lifecycles(session)
        months_range = build_month_range(SNAPSHOT_MONTHS)
        snapshot = {
            "headcount_trend": [
                item.model_dump()
                for item in compute_headcount_trend(lifecycles, months_range)
            ],
            "turnover": [
                item.model_dump()
                for item in compute_turnover(lifecycles, months_range)
            ],
            "computed_at": date.today().isoformat(),
        }
        await self._write_snapshot("personnel", snapshot)
        return snapshot

    async def _load_lifecycles(
        self, session: AsyncSession, *, org_ids: list[str] | None = None
    ) -> list[tuple[date, date | None]]:
        stmt = select(Employee.hire_date, Employee.offboard_date).where(
            Employee.hire_date.is_not(None)
        )
        if org_ids is not None:
            stmt = stmt.where(Employee.org_id.in_(org_ids))
        rows = (await session.execute(stmt)).all()
        return [(hire_date, offboard_date) for hire_date, offboard_date in rows]

    async def _resolve_org_ids(
        self, session: AsyncSession, org_id: str | None
    ) -> list[str] | None:
        """org_id → 子树拍平 id 集；无下钻返回 None（全组织口径）。"""
        if not org_id:
            return None
        return await employee_service.expand_org_ids(session, org_id)

    async def _personnel_series(
        self,
        session: AsyncSession,
        months_range: list[date],
        *,
        org_ids: list[str] | None,
        field: str,
    ) -> list[dict]:
        """趋势/离职率序列：全组织口径走快照切片（窗口不覆盖回源），下钻实时计算。"""
        if org_ids is None:
            snapshot = await self._get_snapshot(session)
            sliced = _slice_series(snapshot[field], months_range)
            if sliced is not None:
                return sliced
        lifecycles = await self._load_lifecycles(session, org_ids=org_ids)
        compute = (
            compute_headcount_trend if field == "headcount_trend" else compute_turnover
        )
        return [item.model_dump() for item in compute(lifecycles, months_range)]

    # ── 快照缓存 ──

    async def _read_snapshot(self, domain: str) -> dict | None:
        try:
            raw = await RedisUtil.get(f"{SNAPSHOT_KEY_PREFIX}{domain}")
        except Exception:  # noqa: BLE001 缓存不可用走实时
            return None
        if not raw:
            return None
        try:
            return json.loads(raw) or None
        except json.JSONDecodeError:
            return None

    async def _write_snapshot(self, domain: str, payload: dict) -> None:
        try:
            await RedisUtil.set(
                f"{SNAPSHOT_KEY_PREFIX}{domain}",
                json.dumps(payload, ensure_ascii=False),
                ttl=SNAPSHOT_TTL_SECONDS,
            )
        except Exception:  # noqa: BLE001 缓存失败不影响接口
            pass

    # ── 招聘域 ──

    async def get_recruiting(
        self,
        session: AsyncSession,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        org_id: str | None = None,
    ) -> RecruitingReportResponse:
        org_ids = await self._resolve_org_ids(session, org_id)
        if org_ids is None and date_from and date_to:
            bucketed = await self._recruiting_from_snapshot(date_from, date_to)
            if bucketed is not None:
                return bucketed
        return await self._recruiting_realtime(
            session, date_from=date_from, date_to=date_to, org_ids=org_ids
        )

    async def _recruiting_from_snapshot(
        self, date_from: date, date_to: date
    ) -> RecruitingReportResponse | None:
        """快照月度桶聚合：区间各月桶齐全才可用，缺桶/越界返回 None 回源实时。"""
        cached = await self._read_snapshot("recruiting")
        months_payload = (cached or {}).get("months") or {}
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        labels = [
            _month_label(value)
            for value in build_month_range_from_interval(date_from, date_to)
        ]
        if not labels or any(label not in months_payload for label in labels):
            return None
        funnel_counts: dict[str, int] = {}
        channel_counts: dict[str | None, dict[str, int]] = {}
        for label in labels:
            bucket = months_payload[label]
            for stage, count in (bucket.get("funnel") or {}).items():
                funnel_counts[stage] = funnel_counts.get(stage, 0) + count
            for channel, stages in (bucket.get("channels") or {}).items():
                target = channel_counts.setdefault(channel, {})
                for stage, count in stages.items():
                    target[stage] = target.get(stage, 0) + count
        stage_order = requisition_service._stage_order()
        funnel = [
            FunnelStageCount(stage=stage, count=funnel_counts.get(stage, 0))
            for stage in stage_order
        ]
        channels = [
            ChannelStageCount(channel=channel, stages=stages)
            for channel, stages in sorted(
                channel_counts.items(),
                key=lambda item: -sum(item[1].values()),
            )
        ]
        return RecruitingReportResponse(funnel=funnel, channels=channels)

    async def _recruiting_realtime(
        self,
        session: AsyncSession,
        *,
        date_from: date | None,
        date_to: date | None,
        org_ids: list[str] | None,
    ) -> RecruitingReportResponse:
        conditions = []
        if date_from:
            conditions.append(CandidateApplication.apply_time >= _day_start(date_from))
        if date_to:
            conditions.append(CandidateApplication.apply_time < _day_end(date_to))

        stage_stmt = select(CandidateApplication.stage, func.count())
        channel_stmt = select(
            Candidate.source_channel,
            CandidateApplication.stage,
            func.count(),
        ).join(Candidate, CandidateApplication.candidate_id == Candidate.id)
        if org_ids is not None:
            stage_stmt = stage_stmt.join(
                JobRequisition,
                CandidateApplication.requisition_id == JobRequisition.id,
            )
            channel_stmt = channel_stmt.join(
                JobRequisition,
                CandidateApplication.requisition_id == JobRequisition.id,
            ).where(JobRequisition.org_id.in_(org_ids))

        stage_rows = (
            await session.execute(
                stage_stmt.where(*conditions).group_by(CandidateApplication.stage)
            )
        ).all()
        counts = {stage: count for stage, count in stage_rows}
        stage_order = requisition_service._stage_order()
        funnel = [
            FunnelStageCount(stage=stage, count=counts.get(stage, 0))
            for stage in stage_order
        ]

        channel_rows = (
            await session.execute(
                channel_stmt.where(*conditions).group_by(
                    Candidate.source_channel, CandidateApplication.stage
                )
            )
        ).all()
        channel_map: dict[str | None, dict[str, int]] = {}
        for channel, stage, count in channel_rows:
            channel_map.setdefault(channel, {})[stage] = count
        channels = [
            ChannelStageCount(channel=channel, stages=stages)
            for channel, stages in sorted(
                channel_map.items(),
                key=lambda item: -sum(item[1].values()),
            )
        ]
        return RecruitingReportResponse(funnel=funnel, channels=channels)

    async def compute_recruiting_snapshot(self, session: AsyncSession) -> dict:
        """招聘域快照（近 12 个月度桶：漏斗+渠道），供快照任务回写。"""
        months_range = build_month_range(SNAPSHOT_MONTHS)
        month_expr = func.to_char(
            CandidateApplication.apply_time, "YYYY-MM"
        ).label("month")
        since = _day_start(months_range[0])
        stage_rows = (
            await session.execute(
                select(month_expr, CandidateApplication.stage, func.count())
                .where(CandidateApplication.apply_time >= since)
                .group_by(month_expr, CandidateApplication.stage)
            )
        ).all()
        channel_rows = (
            await session.execute(
                select(
                    month_expr,
                    Candidate.source_channel,
                    CandidateApplication.stage,
                    func.count(),
                )
                .join(Candidate, CandidateApplication.candidate_id == Candidate.id)
                .where(CandidateApplication.apply_time >= since)
                .group_by(
                    month_expr, Candidate.source_channel, CandidateApplication.stage
                )
            )
        ).all()
        months: dict[str, dict] = {}
        for month, stage, count in stage_rows:
            bucket = months.setdefault(month, {"funnel": {}, "channels": {}})
            bucket["funnel"][stage] = count
        for month, channel, stage, count in channel_rows:
            bucket = months.setdefault(month, {"funnel": {}, "channels": {}})
            bucket["channels"].setdefault(channel, {})[stage] = count
        return {
            "window": [
                months_range[0].isoformat(),
                _month_end(months_range[-1]).isoformat(),
            ],
            "months": months,
            "computed_at": date.today().isoformat(),
        }

    # ── 薪酬分布（脱敏聚合）──

    async def get_comp_distribution(self, session: AsyncSession) -> CompDistResponse:
        """薪酬分布：快照优先（miss/结构损坏回源实时并回填）。"""
        cached = await self._read_snapshot("compensation")
        if cached is not None:
            try:
                return CompDistResponse(**cached)
            except Exception:  # noqa: BLE001 快照结构损坏回源
                pass
        result = await self.compute_comp_distribution(session)
        await self._write_snapshot("compensation", result.model_dump())
        return result

    async def compute_comp_distribution(
        self, session: AsyncSession
    ) -> CompDistResponse:
        today = date.today()
        totals = (
            select(
                EmployeeSalaryPackage.employee_id,
                func.sum(EmployeeSalaryPackage.amount).label("total_amount"),
            )
            .where(
                EmployeeSalaryPackage.effective_from <= today,
                (EmployeeSalaryPackage.effective_to.is_(None))
                | (EmployeeSalaryPackage.effective_to >= today),
            )
            .group_by(EmployeeSalaryPackage.employee_id)
            .subquery()
        )
        by_level = await self._comp_dist(session, totals, Employee.job_level)
        by_org = await self._comp_dist(session, totals, Employee.org_id)
        return CompDistResponse(by_level=by_level, by_org=by_org)

    async def _comp_dist(
        self,
        session: AsyncSession,
        totals,
        slice_column,
    ) -> list[CompDistItem]:
        rows = (
            await session.execute(
                select(
                    slice_column,
                    func.count(totals.c.employee_id),
                    func.min(totals.c.total_amount),
                    func.avg(totals.c.total_amount),
                    func.max(totals.c.total_amount),
                )
                .join(Employee, totals.c.employee_id == Employee.id)
                .group_by(slice_column)
            )
        ).all()
        return [
            CompDistItem(
                key=str(key) if key else None,
                count=count,
                min_amount=round(float(min_amount), 2),
                mid_amount=round(float(avg_amount), 2),
                max_amount=round(float(max_amount), 2),
            )
            for key, count, min_amount, avg_amount, max_amount in rows
        ]

    # ── 绩效分布（closed 周期）──

    async def get_performance(self, session: AsyncSession) -> PerformanceReportResponse:
        """绩效报表：快照优先（miss/结构损坏回源实时并回填）；metric_ref 现场读口径同源。"""
        cached = await self._read_snapshot("performance")
        if cached is not None:
            try:
                result = PerformanceReportResponse(**cached)
                result.metric_ref = await self._metric_ref(
                    session, "perf_rating_distribution"
                )
                return result
            except Exception:  # noqa: BLE001 快照结构损坏回源
                pass
        result = await self.compute_performance(session)
        result.metric_ref = await self._metric_ref(session, "perf_rating_distribution")
        await self._write_snapshot("performance", result.model_dump())
        return result

    async def compute_performance(
        self, session: AsyncSession
    ) -> PerformanceReportResponse:
        """closed 周期绩效汇总：评级分布（calibrated_rating 优先回退 rating）+
        周期均分趋势（按周期截止日升序）。"""
        rows = (
            await session.execute(
                select(
                    PerfCycle.id,
                    PerfCycle.name,
                    PerfCycle.end_date,
                    PerfReview.rating,
                    PerfReview.calibrated_rating,
                    PerfReview.score,
                )
                .join(PerfReview, PerfReview.cycle_id == PerfCycle.id)
                .where(PerfCycle.status == "closed")
                .order_by(PerfCycle.end_date, PerfReview.created_at)
            )
        ).all()

        cycle_map: dict[str, dict] = {}
        for cycle_id, name, end_date, rating, calibrated, score in rows:
            entry = cycle_map.setdefault(
                cycle_id,
                {"name": name, "end_date": end_date, "total": 0, "scores": [], "ratings": {}},
            )
            entry["total"] += 1
            effective_rating = calibrated or rating
            if effective_rating:
                entry["ratings"][effective_rating] = (
                    entry["ratings"].get(effective_rating, 0) + 1
                )
            if score is not None:
                entry["scores"].append(score)

        cycles = [
            CyclePerformanceItem(
                cycle_id=cycle_id,
                cycle_name=entry["name"],
                end_date=entry["end_date"],
                total=entry["total"],
                avg_score=(
                    round(
                        sum(entry["scores"]) / len(entry["scores"]), 1
                    )
                    if entry["scores"]
                    else None
                ),
                ratings=entry["ratings"],
            )
            for cycle_id, entry in cycle_map.items()
        ]
        return PerformanceReportResponse(cycles=cycles)


report_service = ReportService()
