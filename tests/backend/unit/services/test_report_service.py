"""报表服务单元测试

覆盖：月序列构造（months 回溯 / 真日期区间整月展开）、在编趋势回算（月末口径）、
离职率口径（当月离职/平均在编）、漏斗统计与候选人页同源口径（stage 顺序复用
requisition_service）、分渠道阶段计数、薪酬分布脱敏聚合（仅 min/mid/max）、
快照缓存 miss 回源、窗口覆盖切片（越界回源实时）、招聘月度桶聚合。
"""

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.tenant.context import TenantContext

from hr.services.report_service import (
    build_month_range,
    build_month_range_from_interval,
    compute_headcount_trend,
    compute_turnover,
    report_service,
    resolve_month_range,
)


class _FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one(self):
        if self._scalar is not None:
            return self._scalar
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


def _mock_session(execute_results=None) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.execute = AsyncMock(
        side_effect=list(execute_results) if execute_results else []
    )
    return session


@pytest.fixture(autouse=True)
def _tenant_context():
    TenantContext.set_tenant_id("t-1")
    yield
    TenantContext.clear()


class TestBuildMonthRange:
    """月序列构造"""

    def test_recent_months_ascending_includes_current(self):
        result = build_month_range(6, today=date(2026, 10, 16))
        assert result[0] == date(2026, 5, 1)
        assert result[-1] == date(2026, 10, 1)
        assert len(result) == 6

    def test_spans_year_boundary(self):
        result = build_month_range(3, today=date(2026, 1, 15))
        assert [item.month for item in result] == [11, 12, 1]

    def test_interval_expands_intersecting_months(self):
        result = build_month_range_from_interval(
            date(2026, 9, 15), date(2027, 1, 5)
        )
        assert result == [
            date(2026, 9, 1),
            date(2026, 10, 1),
            date(2026, 11, 1),
            date(2026, 12, 1),
            date(2027, 1, 1),
        ]

    def test_interval_single_month(self):
        result = build_month_range_from_interval(
            date(2026, 10, 2), date(2026, 10, 18)
        )
        assert result == [date(2026, 10, 1)]

    def test_resolve_prefers_interval_over_months(self):
        result = resolve_month_range(date(2026, 7, 1), date(2026, 8, 31), 6)
        assert [value.strftime("%Y-%m") for value in result] == [
            "2026-07",
            "2026-08",
        ]

    def test_resolve_swaps_reversed_interval(self):
        result = resolve_month_range(date(2026, 8, 31), date(2026, 7, 1), 6)
        assert [value.strftime("%Y-%m") for value in result] == [
            "2026-07",
            "2026-08",
        ]

    def test_resolve_falls_back_to_months(self):
        result = resolve_month_range(None, None, 3)
        assert len(result) == 3


class TestHeadcountTrend:
    """在编趋势回算（月末口径）"""

    def test_hire_and_offboard_boundaries(self):
        lifecycles = [
            (date(2020, 1, 1), None),                # A 全程在编
            (date(2020, 1, 1), date(2026, 5, 15)),   # B 5 月离职
            (date(2026, 4, 10), None),               # C 4 月中入职
        ]
        months_range = build_month_range(3, today=date(2026, 6, 30))
        trend = compute_headcount_trend(lifecycles, months_range)
        assert [point.count for point in trend] == [3, 2, 2]
        assert [point.month for point in trend] == ["2026-04", "2026-05", "2026-06"]

    def test_future_hire_not_counted(self):
        lifecycles = [(date(2026, 12, 1), None)]
        months_range = build_month_range(2, today=date(2026, 10, 16))
        trend = compute_headcount_trend(lifecycles, months_range)
        assert all(point.count == 0 for point in trend)


class TestTurnover:
    """离职率口径"""

    def test_rate_is_monthly_offboard_over_avg_headcount(self):
        lifecycles = [
            (date(2020, 1, 1), None),
            (date(2020, 1, 1), date(2026, 5, 15)),
            (date(2026, 4, 10), None),
        ]
        months_range = build_month_range(3, today=date(2026, 6, 30))
        points = compute_turnover(lifecycles, months_range)
        assert points[1].month == "2026-05"
        assert points[1].offboarded == 1
        assert points[1].avg_headcount == 2
        assert points[1].rate == 50.0
        assert points[0].offboarded == 0
        assert points[0].rate == 0.0

    def test_zero_headcount_rate_is_none(self):
        points = compute_turnover([], build_month_range(2, today=date(2026, 10, 16)))
        assert all(point.rate is None for point in points)
        assert all(point.avg_headcount == 0 for point in points)


class TestOverview:
    """人事仪表盘"""

    @pytest.mark.asyncio
    async def test_miss_computes_and_caches(self):
        stats = MagicMock()
        stats.model_dump.return_value = {}
        session = _mock_session(
            execute_results=[
                _FakeResult(rows=[(date(2020, 1, 1), None)]),    # 生命周期（miss 回源）
                _FakeResult(rows=[("org-1", 3), ("org-2", 1)]),  # 组织分布
            ]
        )
        with (
            patch(
                "hr.services.employee_service.employee_service.get_stats",
                new=AsyncMock(return_value=stats),
            ),
            patch(
                "hr.services.report_service.RedisUtil.get", new=AsyncMock(return_value=None)
            ) as redis_get,
            patch(
                "hr.services.report_service.RedisUtil.set", new=AsyncMock()
            ) as redis_set,
        ):
            result = await report_service.get_overview(session, months=6)
        redis_get.assert_awaited_once()
        redis_set.assert_awaited_once()
        assert len(result.headcount_trend) == 6
        assert result.headcount_trend[-1].month == date.today().strftime("%Y-%m")
        assert [item.org_id for item in result.org_distribution] == ["org-1", "org-2"]

    @pytest.mark.asyncio
    async def test_cache_hit_slices_requested_interval(self):
        """缓存命中：真日期区间完整落在快照窗口内 → 按区间切片返回。"""
        months = [f"2026-{month:02d}" for month in range(1, 13)]
        payload = {
            "headcount_trend": [{"month": month, "count": 1} for month in months],
            "turnover": [
                {"month": month, "offboarded": 0, "avg_headcount": 1, "rate": 0.0}
                for month in months
            ],
        }
        stats = MagicMock()
        stats.model_dump.return_value = {}
        session = _mock_session(
            execute_results=[_FakeResult(rows=[])]  # 组织分布
        )
        with (
            patch(
                "hr.services.employee_service.employee_service.get_stats",
                new=AsyncMock(return_value=stats),
            ),
            patch(
                "hr.services.report_service.RedisUtil.get",
                new=AsyncMock(return_value=json.dumps(payload)),
            ),
        ):
            result = await report_service.get_overview(
                session, date_from=date(2026, 7, 1), date_to=date(2026, 12, 31)
            )
        assert [point.month for point in result.headcount_trend] == [
            "2026-07", "2026-08", "2026-09", "2026-10", "2026-11", "2026-12"
        ]

    @pytest.mark.asyncio
    async def test_interval_beyond_window_falls_back_realtime(self):
        """区间超出快照窗口 → 切片返回 None，回源实时计算不回写快照。"""
        months = [f"2026-{month:02d}" for month in range(1, 13)]
        payload = {
            "headcount_trend": [{"month": month, "count": 1} for month in months],
            "turnover": [
                {"month": month, "offboarded": 0, "avg_headcount": 1, "rate": 0.0}
                for month in months
            ],
        }
        stats = MagicMock()
        stats.model_dump.return_value = {}
        session = _mock_session(
            execute_results=[
                _FakeResult(rows=[]),                            # 生命周期（实时回源）
                _FakeResult(rows=[]),                            # 组织分布
            ]
        )
        with (
            patch(
                "hr.services.employee_service.employee_service.get_stats",
                new=AsyncMock(return_value=stats),
            ),
            patch(
                "hr.services.report_service.RedisUtil.get",
                new=AsyncMock(return_value=json.dumps(payload)),
            ) as redis_get,
            patch(
                "hr.services.report_service.RedisUtil.set", new=AsyncMock()
            ) as redis_set,
        ):
            result = await report_service.get_overview(
                session, date_from=date(2027, 1, 1), date_to=date(2027, 3, 31)
            )
        redis_get.assert_awaited_once()
        redis_set.assert_not_awaited()
        assert [point.month for point in result.headcount_trend] == [
            "2027-01", "2027-02", "2027-03"
        ]

    @pytest.mark.asyncio
    async def test_turnover_reuses_snapshot(self):
        # 快照月桶取当月（months=1 窗口即当月；硬编码月份会随时间推移切片脱窗）
        month = date.today().strftime("%Y-%m")
        payload = {
            "headcount_trend": [{"month": month, "count": 10}],
            "turnover": [
                {"month": month, "offboarded": 2, "avg_headcount": 10, "rate": 20.0}
            ],
        }
        session = _mock_session()
        with patch(
            "hr.services.report_service.RedisUtil.get",
            new=AsyncMock(return_value=json.dumps(payload)),
        ):
            result = await report_service.get_turnover(session, months=1)
        assert len(result.points) == 1
        assert result.points[0].rate == 20.0


class TestRecruiting:
    """招聘漏斗与渠道转化"""

    @pytest.mark.asyncio
    async def test_funnel_uses_candidate_page_stage_order(self):
        session = _mock_session(
            execute_results=[
                _FakeResult(rows=[("onboarded", 2), ("pending_screening", 5)]),
                _FakeResult(rows=[("neibu", "onboarded", 2), ("neibu", "pending_screening", 5)]),
            ]
        )
        result = await report_service.get_recruiting(session)
        stages = [item.stage for item in result.funnel]
        # 与 requisition_service._stage_order() 同序（与候选人页口径一致）
        assert stages[0] == "pending_screening"
        assert stages.index("interviewing") < stages.index("offered")
        assert result.funnel[0].count == 5
        assert result.funnel[-1].count == 0  # withdrawn 无数据补零
        assert result.channels[0].channel == "neibu"
        assert result.channels[0].stages == {"onboarded": 2, "pending_screening": 5}

    @pytest.mark.asyncio
    async def test_interval_aggregates_snapshot_month_buckets(self):
        """区间各月桶齐全 → 快照月度桶逐月聚合，不落库查询。"""
        payload = {
            "window": ["2026-09-01", "2026-10-31"],
            "months": {
                "2026-09": {
                    "funnel": {"pending_screening": 3, "onboarded": 1},
                    "channels": {"neibu": {"pending_screening": 3}},
                },
                "2026-10": {
                    "funnel": {"pending_screening": 2},
                    "channels": {
                        "zhilian": {"pending_screening": 2},
                        "neibu": {"onboarded": 1},
                    },
                },
            },
        }
        session = _mock_session()
        with patch(
            "hr.services.report_service.RedisUtil.get",
            new=AsyncMock(return_value=json.dumps(payload)),
        ):
            result = await report_service.get_recruiting(
                session,
                date_from=date(2026, 9, 15),
                date_to=date(2026, 10, 14),
            )
        session.execute.assert_not_awaited()
        funnel_counts = {item.stage: item.count for item in result.funnel}
        assert funnel_counts["pending_screening"] == 5
        assert funnel_counts["onboarded"] == 1
        assert funnel_counts["interviewing"] == 0  # 无数据补零
        assert [channel.channel for channel in result.channels] == ["neibu", "zhilian"]
        assert result.channels[0].stages == {"pending_screening": 3, "onboarded": 1}

    @pytest.mark.asyncio
    async def test_missing_bucket_falls_back_realtime(self):
        """区间存在缺桶月份 → 回源实时查询。"""
        payload = {
            "window": ["2026-09-01", "2026-10-31"],
            "months": {
                "2026-10": {"funnel": {"pending_screening": 2}, "channels": {}},
            },
        }
        session = _mock_session(
            execute_results=[
                _FakeResult(rows=[("pending_screening", 7)]),
                _FakeResult(rows=[("neibu", "pending_screening", 7)]),
            ]
        )
        with (
            patch(
                "hr.services.report_service.RedisUtil.get",
                new=AsyncMock(return_value=json.dumps(payload)),
            ),
        ):
            result = await report_service.get_recruiting(
                session,
                date_from=date(2026, 8, 1),
                date_to=date(2026, 10, 31),
            )
        session.execute.assert_awaited()
        assert result.funnel[0].count == 7


class TestCompDist:
    """薪酬分布（脱敏聚合）"""

    @pytest.mark.asyncio
    async def test_aggregate_only_min_mid_max(self):
        session = _mock_session(
            execute_results=[
                _FakeResult(rows=[("P5", 2, 8000, 9000, 10000)]),
                _FakeResult(rows=[("org-1", 3, 7000, 8500, 12000)]),
            ]
        )
        with (
            patch(
                "hr.services.report_service.RedisUtil.get",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "hr.services.report_service.RedisUtil.set", new=AsyncMock()
            ) as redis_set,
        ):
            result = await report_service.get_comp_distribution(session)
        assert result.by_level[0].key == "P5"
        assert result.by_level[0].count == 2
        assert result.by_level[0].min_amount == 8000.0
        assert result.by_level[0].mid_amount == 9000.0
        assert result.by_level[0].max_amount == 10000.0
        assert result.by_org[0].key == "org-1"
        # 脱敏：响应模型无个人粒度字段
        assert "employee_id" not in result.by_level[0].model_dump()
        # miss 回源后回填快照
        redis_set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_snapshot_hit_skips_db(self):
        payload = {
            "by_level": [{"key": "P5", "count": 2, "min_amount": 8000.0,
                          "mid_amount": 9000.0, "max_amount": 10000.0}],
            "by_org": [],
        }
        session = _mock_session()
        with patch(
            "hr.services.report_service.RedisUtil.get",
            new=AsyncMock(return_value=json.dumps(payload)),
        ):
            result = await report_service.get_comp_distribution(session)
        session.execute.assert_not_awaited()
        assert result.by_level[0].key == "P5"


class TestPerformance:
    """绩效报表（closed 周期评级分布 + 周期均分趋势）"""

    @pytest.mark.asyncio
    async def test_closed_cycles_with_calibrated_rating_preferred(self):
        """评级取 calibrated_rating 优先回退 rating；均分=非空得分均值。"""
        session = _mock_session(
            execute_results=[
                _FakeResult(
                    rows=[
                        # cyc-1（升序在前）：初评 A、校准 B、得分 80
                        ("cyc-1", "2026-H1", date(2026, 6, 30), "A", None, 80),
                        ("cyc-1", "2026-H1", date(2026, 6, 30), "C", "B", 90),
                        # cyc-2（后收口）：仅初评 S，无得分
                        ("cyc-2", "2026-H2", date(2026, 12, 31), "S", None, None),
                    ]
                )
            ]
        )
        with (
            patch(
                "hr.services.report_service.RedisUtil.get",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "hr.services.report_service.RedisUtil.set", new=AsyncMock()
            ),
        ):
            result = await report_service.get_performance(session)
        assert [c.cycle_id for c in result.cycles] == ["cyc-1", "cyc-2"]
        first = result.cycles[0]
        assert first.total == 2
        assert first.avg_score == 85.0
        assert first.ratings == {"B": 1, "A": 1}  # 校准覆盖 + 未校准回退初评
        second = result.cycles[1]
        assert second.total == 1
        assert second.avg_score is None
        assert second.ratings == {"S": 1}

    @pytest.mark.asyncio
    async def test_no_closed_cycles_returns_empty(self):
        session = _mock_session(execute_results=[_FakeResult(rows=[])])
        with (
            patch(
                "hr.services.report_service.RedisUtil.get",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "hr.services.report_service.RedisUtil.set", new=AsyncMock()
            ),
        ):
            result = await report_service.get_performance(session)
        assert result.cycles == []
