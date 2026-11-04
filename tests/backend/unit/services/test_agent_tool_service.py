"""agent 工具面单元测试

覆盖：X-Tenant-Id fail-closed、编制/在编概览（含子组织展开）、候选人检索
（脱敏与 limit 裁剪）、漏斗统计复用、员工档案摘要敏感字段不出面。
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
)
from framework.tenant.context import TenantContext

from hr.models import Candidate, Employee
from hr.schemas.recruiting import FunnelResponse, FunnelStat
from hr.schemas.report import (
    CompDistItem,
    CompDistResponse,
    CyclePerformanceItem,
    PerformanceReportResponse,
    TurnoverPoint,
    TurnoverResponse,
)
from hr.services.agent_tool_service import (
    _mask_email,
    _mask_phone,
    agent_tool_service,
)


class _FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one(self):
        if self._scalar is not None:
            return self._scalar
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


def _mock_session(get_map=None, execute_results=None) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)

    async def _get(model, pk):
        return (get_map or {}).get((model.__name__, str(pk)))

    session.get = AsyncMock(side_effect=_get)
    session.execute = AsyncMock(
        side_effect=list(execute_results) if execute_results else []
    )
    return session


def _employee(**overrides) -> Employee:
    defaults = dict(
        id="emp-1",
        tenant_id="t-1",
        employee_no="EMP0001",
        name="张三",
        phone="13800001111",
        id_card_enc="cipher",
        bank_card_enc="cipher",
        status="probation",
        hire_date=date(2026, 1, 5),
    )
    defaults.update(overrides)
    return Employee(**defaults)


class TestTenantFailClosed:
    """缺 X-Tenant-Id 一律拒绝（403 语义）"""

    @pytest.mark.asyncio
    async def test_all_tools_reject_without_tenant(self):
        TenantContext.clear()
        session = _mock_session()
        with pytest.raises(ForbiddenError):
            await agent_tool_service.headcount(session)
        with pytest.raises(ForbiddenError):
            await agent_tool_service.search_candidates(session)
        with pytest.raises(ForbiddenError):
            await agent_tool_service.recruiting_funnel(session)
        with pytest.raises(ForbiddenError):
            await agent_tool_service.employee_profile(session, "emp-1")


class TestHeadcount:
    """编制与在编概览"""

    @pytest.mark.asyncio
    async def test_company_wide(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session(
            execute_results=[_FakeResult(scalar=10), _FakeResult(scalar=7)]
        )
        result = await agent_tool_service.headcount(session)
        assert result == {
            "org_id": None,
            "headcount": 10,
            "active_employees": 7,
            "vacancy": 3,
        }

    @pytest.mark.asyncio
    async def test_with_org_expands_children(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session(
            execute_results=[_FakeResult(scalar=4), _FakeResult(scalar=5)]
        )
        with patch(
            "hr.services.employee_service.employee_service.expand_org_ids",
            new=AsyncMock(return_value=["org-1", "org-1-1"]),
        ) as expand:
            result = await agent_tool_service.headcount(session, org_id="org-1")
        expand.assert_awaited_once()
        assert result["org_id"] == "org-1"
        assert result["vacancy"] == -1  # 超编不裁剪，如实报告


class TestSearchCandidates:
    """候选人检索（脱敏）"""

    @pytest.mark.asyncio
    async def test_masks_contact_fields(self):
        TenantContext.set_tenant_id("t-1")
        rows = [
            Candidate(
                id="cand-1", tenant_id="t-1", name="张三",
                phone="13800001111", email="zhangsan@example.com",
                source_channel="zhilian",
            ),
            Candidate(
                id="cand-2", tenant_id="t-1", name="李四",
                source_channel="manual",
            ),
        ]
        session = _mock_session(execute_results=[_FakeResult(rows=rows)])
        result = await agent_tool_service.search_candidates(session, q="张")
        assert result["count"] == 2
        assert result["items"][0]["phone_masked"] == "138****1111"
        assert result["items"][0]["email_masked"] == "z***@example.com"
        assert result["items"][1]["phone_masked"] is None

    @pytest.mark.asyncio
    async def test_limit_clamped(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session(execute_results=[_FakeResult(rows=[])])
        await agent_tool_service.search_candidates(session, limit=99)
        stmt = session.execute.await_args.args[0]
        assert stmt._limit_clause.value == 20


class TestRecruitingFunnel:
    """漏斗统计（复用需求域口径）"""

    @pytest.mark.asyncio
    async def test_global_funnel(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session()
        funnel = FunnelResponse(
            requisition_id=None,
            stats=[FunnelStat(stage="pending_screening", count=3)],
        )
        with patch(
            "hr.services.requisition_service.requisition_service.get_funnel",
            new=AsyncMock(return_value=funnel),
        ) as get_funnel:
            result = await agent_tool_service.recruiting_funnel(session)
        get_funnel.assert_awaited_once_with(session, None)
        assert result["stats"] == [{"stage": "pending_screening", "count": 3}]
        assert "requisition_title" not in result

    @pytest.mark.asyncio
    async def test_single_requisition_includes_title(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session()
        funnel = FunnelResponse(
            requisition_id="req-1",
            stats=[FunnelStat(stage="interviewing", count=2)],
        )
        requisition = MagicMock()
        requisition.title = "Python 工程师"
        with (
            patch(
                "hr.services.requisition_service.requisition_service.get_funnel",
                new=AsyncMock(return_value=funnel),
            ),
            patch(
                "hr.services.requisition_service.requisition_service.get_requisition",
                new=AsyncMock(return_value=requisition),
            ),
        ):
            result = await agent_tool_service.recruiting_funnel(
                session, requisition_id="req-1"
            )
        assert result["requisition_title"] == "Python 工程师"


class TestEmployeeProfile:
    """员工档案摘要（敏感字段不出面）"""

    @pytest.mark.asyncio
    async def test_profile_masks_sensitive(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session(get_map={("Employee", "emp-1"): _employee()})
        profile = await agent_tool_service.employee_profile(session, "emp-1")
        assert profile["employee_no"] == "EMP0001"
        assert profile["phone_masked"] == "138****1111"
        assert "id_card" not in profile
        assert "bank_card" not in profile
        assert profile["status"] == "probation"

    @pytest.mark.asyncio
    async def test_not_found(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session()
        with pytest.raises(NotFoundError):
            await agent_tool_service.employee_profile(session, "emp-404")


class TestMaskHelpers:
    """脱敏纯函数"""

    def test_mask_phone(self):
        assert _mask_phone("13800001111") == "138****1111"
        assert _mask_phone("1234567") == "12****"
        assert _mask_phone(None) is None

    def test_mask_email(self):
        assert _mask_email("zhangsan@example.com") == "z***@example.com"
        assert _mask_email(None) is None
        assert _mask_email("no-at-sign") == "***"


class TestReportTools:
    """报表三域工具扩面（离职率序列/薪酬分布/绩效概览，报表同源口径）"""

    @pytest.mark.asyncio
    async def test_new_tools_reject_without_tenant(self):
        TenantContext.clear()
        session = _mock_session()
        with pytest.raises(ForbiddenError):
            await agent_tool_service.turnover_stats(session)
        with pytest.raises(ForbiddenError):
            await agent_tool_service.comp_distribution(session)
        with pytest.raises(ForbiddenError):
            await agent_tool_service.performance_summary(session)

    @pytest.mark.asyncio
    async def test_turnover_stats_delegates_to_report(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session()
        turnover = TurnoverResponse(
            points=[TurnoverPoint(month="2026-09", offboarded=2, avg_headcount=100, rate=2.0)]
        )
        with patch(
            "hr.services.report_service.report_service.get_turnover",
            new=AsyncMock(return_value=turnover),
        ) as mock_get:
            result = await agent_tool_service.turnover_stats(session, months=6)
        mock_get.assert_awaited_once_with(session, months=6)
        assert result["months"] == 6
        assert result["points"][0]["rate"] == 2.0
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_turnover_stats_clamps_months(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session()
        with patch(
            "hr.services.report_service.report_service.get_turnover",
            new=AsyncMock(return_value=TurnoverResponse(points=[])),
        ) as mock_get:
            result = await agent_tool_service.turnover_stats(session, months=99)
        mock_get.assert_awaited_once_with(session, months=12)
        assert result["months"] == 12

    @pytest.mark.asyncio
    async def test_comp_distribution_by_level(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session()
        comp = CompDistResponse(
            by_level=[
                CompDistItem(
                    key="P6", count=3,
                    min_amount=10000, mid_amount=15000, max_amount=20000,
                )
            ],
            by_org=[],
        )
        with patch(
            "hr.services.report_service.report_service.get_comp_distribution",
            new=AsyncMock(return_value=comp),
        ) as mock_get:
            result = await agent_tool_service.comp_distribution(session, by="job_level")
        mock_get.assert_awaited_once_with(session)
        assert result["by"] == "job_level"
        item = result["items"][0]
        assert item == {
            "key": "P6", "count": 3,
            "min_amount": 10000, "mid_amount": 15000, "max_amount": 20000,
        }

    @pytest.mark.asyncio
    async def test_comp_distribution_invalid_by_rejected(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session()
        with pytest.raises(BadRequestError, match="job_level/org"):
            await agent_tool_service.comp_distribution(session, by="salary")

    @pytest.mark.asyncio
    async def test_performance_summary_delegates_to_report(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session()
        perf = PerformanceReportResponse(
            cycles=[
                CyclePerformanceItem(
                    cycle_id="c-1", cycle_name="2026H1", total=10,
                    avg_score=85.5, ratings={"A": 3, "B": 5},
                )
            ]
        )
        with patch(
            "hr.services.report_service.report_service.get_performance",
            new=AsyncMock(return_value=perf),
        ) as mock_get:
            result = await agent_tool_service.performance_summary(session)
        mock_get.assert_awaited_once_with(session)
        assert result["cycles"][0]["cycle_name"] == "2026H1"
        assert result["cycles"][0]["avg_score"] == 85.5
