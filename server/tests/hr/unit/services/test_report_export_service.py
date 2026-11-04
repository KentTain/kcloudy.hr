"""报表导出服务单元测试

覆盖：六域行集组装（复用各域 get_* 同口径）、xlsx 头行与分段布局、
attrition-risk include_comp 透传、未知域拒绝、文件名规则。
"""

from datetime import date
from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from openpyxl import load_workbook

from hr.schemas.report import (
    AttritionRiskItem,
    AttritionRiskResponse,
    ChannelStageCount,
    CompDistItem,
    CompDistResponse,
    CyclePerformanceItem,
    EmployeeStatsResponse,
    FunnelStageCount,
    OverviewResponse,
    PerformanceReportResponse,
    RecruitingReportResponse,
    TrendPoint,
    TurnoverPoint,
    TurnoverResponse,
    OrgDistributionItem,
)
from hr.services.report_export_service import report_export_service


def _overview() -> OverviewResponse:
    return OverviewResponse(
        cards=EmployeeStatsResponse(
            active_count=120, probation_count=8, month_hired_count=3, turnover_rate=0.035
        ),
        headcount_trend=[TrendPoint(month="2026-09", count=115), TrendPoint(month="2026-10", count=120)],
        org_distribution=[OrgDistributionItem(org_id="org-1", count=45)],
    )


class TestBuildExport:
    """六域导出"""

    @pytest.mark.asyncio
    async def test_unknown_domain_rejected(self):
        session = AsyncMock()
        with pytest.raises(ValueError, match="未知导出域"):
            await report_export_service.build_export(session, domain="nope")

    @pytest.mark.asyncio
    async def test_overview_sections_and_filename(self):
        session = AsyncMock()
        with patch(
            "hr.services.report_export_service.report_service.get_overview",
            new=AsyncMock(return_value=_overview()),
        ):
            filename, content = await report_export_service.build_export(
                session, domain="overview", date_from=date(2026, 5, 1), date_to=date(2026, 10, 31)
            )
        assert filename == "报表导出-overview-2026-05-01~2026-10-31.xlsx"
        rows = list(load_workbook(BytesIO(content)).active.iter_rows(values_only=True))
        assert ("指标", "数值") in rows
        assert ("在编人数", 120) in rows
        assert ("月份", "在编人数") in rows
        assert ("2026-10", 120) in rows
        assert ("组织ID", "人数") in rows
        assert ("org-1", 45) in rows

    @pytest.mark.asyncio
    async def test_turnover_rows(self):
        session = AsyncMock()
        turnover = TurnoverResponse(
            points=[TurnoverPoint(month="2026-09", offboarded=1, avg_headcount=100, rate=0.01)]
        )
        with patch(
            "hr.services.report_export_service.report_service.get_turnover",
            new=AsyncMock(return_value=turnover),
        ):
            _, content = await report_export_service.build_export(session, domain="turnover")
        rows = list(load_workbook(BytesIO(content)).active.iter_rows(values_only=True))
        assert rows[0] == ("月份", "离职人数", "月均在编", "离职率")
        assert rows[1] == ("2026-09", 1, 100, 0.01)

    @pytest.mark.asyncio
    async def test_recruiting_channels_flatten_and_none_channel_label(self):
        session = AsyncMock()
        recruiting = RecruitingReportResponse(
            funnel=[FunnelStageCount(stage="pending_screening", count=40)],
            channels=[
                ChannelStageCount(channel=None, stages={"pending_screening": 10}),
                ChannelStageCount(channel="referral", stages={"interviewing": 2, "onboarded": 1}),
            ],
        )
        with patch(
            "hr.services.report_export_service.report_service.get_recruiting",
            new=AsyncMock(return_value=recruiting),
        ):
            _, content = await report_export_service.build_export(session, domain="recruiting")
        rows = list(load_workbook(BytesIO(content)).active.iter_rows(values_only=True))
        assert rows[0][:2] == ("阶段", "人数")
        assert rows[1][:2] == ("pending_screening", 40)
        assert ("未归集渠道", "pending_screening", 10) in rows
        assert ("referral", "onboarded", 1) in rows

    @pytest.mark.asyncio
    async def test_comp_dist_level_and_org_rows(self):
        session = AsyncMock()
        item = CompDistItem(key="P5", count=12, min_amount=10000, mid_amount=15000, max_amount=20000)
        data = CompDistResponse(
            by_level=[item, CompDistItem(key=None, count=3, min_amount=8000, mid_amount=9000, max_amount=10000)],
            by_org=[CompDistItem(key="org-1", count=15, min_amount=9000, mid_amount=14000, max_amount=22000)],
        )
        with patch(
            "hr.services.report_export_service.report_service.get_comp_distribution",
            new=AsyncMock(return_value=data),
        ):
            _, content = await report_export_service.build_export(session, domain="comp-dist")
        rows = list(load_workbook(BytesIO(content)).active.iter_rows(values_only=True))
        assert ("维度", "键", "人数", "下限", "中位", "上限") in rows
        assert ("职级", "P5", 12, 10000, 15000, 20000) in rows
        assert ("职级", "未定级", 3, 8000, 9000, 10000) in rows
        assert ("组织", "org-1", 15, 9000, 14000, 22000) in rows

    @pytest.mark.asyncio
    async def test_performance_cycle_and_rating_sections(self):
        session = AsyncMock()
        data = PerformanceReportResponse(
            cycles=[
                CyclePerformanceItem(
                    cycle_id="cyc-1",
                    cycle_name="2026-H1",
                    end_date=date(2026, 6, 30),
                    total=3,
                    avg_score=85.0,
                    ratings={"S": 1, "A": 2},
                )
            ]
        )
        with patch(
            "hr.services.report_export_service.report_service.get_performance",
            new=AsyncMock(return_value=data),
        ):
            _, content = await report_export_service.build_export(session, domain="performance")
        rows = list(load_workbook(BytesIO(content)).active.iter_rows(values_only=True))
        assert rows[0][:4] == ("周期", "截止日", "参评人数", "平均分")
        assert rows[1][0] == "2026-H1"
        assert rows[1][2] == 3
        assert rows[1][3] == 85
        assert ("周期", "评级", "人数") == rows[3][:3]
        assert ("2026-H1", "S", 1) == rows[4][:3]
        assert ("2026-H1", "A", 2) == rows[5][:3]

    @pytest.mark.asyncio
    async def test_attrition_risk_factors_joined_and_include_comp_passthrough(self):
        session = AsyncMock()
        data = AttritionRiskResponse(
            total=1,
            items=[
                AttritionRiskItem(
                    employee_id="e1",
                    employee_no="E001",
                    name="张三",
                    org_id="org-1",
                    score=65,
                    level="high",
                    factors=["薪酬低于职级薪带下限", "近90天考勤异常≥3次"],
                )
            ],
        )
        with patch(
            "hr.services.report_export_service.attrition_risk_service.get_risk_list",
            new=AsyncMock(return_value=data),
        ) as mock_risk:
            _, content = await report_export_service.build_export(
                session, domain="attrition-risk", org_id="org-1", include_comp=False
            )
        mock_risk.assert_awaited_once_with(session, org_id="org-1", include_comp=False)
        rows = list(load_workbook(BytesIO(content)).active.iter_rows(values_only=True))
        assert rows[0] == ("姓名", "工号", "组织ID", "风险分", "风险等级", "风险因子")
        assert rows[1][:5] == ("张三", "E001", "org-1", 65, "high")
        assert rows[1][5] == "薪酬低于职级薪带下限；近90天考勤异常≥3次"

    @pytest.mark.asyncio
    async def test_filename_without_interval_uses_today(self):
        session = AsyncMock()
        with patch(
            "hr.services.report_export_service.report_service.get_performance",
            new=AsyncMock(return_value=PerformanceReportResponse(cycles=[])),
        ):
            filename, _ = await report_export_service.build_export(session, domain="performance")
        assert filename.startswith("报表导出-performance-")
