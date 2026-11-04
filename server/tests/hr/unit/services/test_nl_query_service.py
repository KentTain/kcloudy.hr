"""NL 问数服务单元测试

覆盖：关键词规则命中（含月数抽取）、白名单越界 400、llm JSON 映射（解析失败
不猜指标）、薪酬域无权限跳过并在回答注明、LLM 回答失败降级模板文案。
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError
from framework.schemas import BaseModel
from framework.tenant.context import TenantContext

from hr.schemas.report import (
    CompDistItem,
    CompDistResponse,
    OverviewResponse,
    TurnoverPoint,
    TurnoverResponse,
)
from hr.services.nl_query_service import nl_query_service


def _mock_session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    return session


class _EmployeeStats(BaseModel):
    active_count: int = 10
    probation_count: int = 2
    month_hired_count: int = 1
    turnover_rate: float = 0.03


class TestKeywordResolve:
    """关键词规则优先"""

    @pytest.mark.asyncio
    async def test_keyword_hit_headcount(self):
        resolved = await nl_query_service.resolve_metric("现在公司有多少在编人员")
        assert resolved is not None
        assert resolved.definition.metric == "headcount"
        assert resolved.source == "keyword"

    @pytest.mark.asyncio
    async def test_keyword_hit_turnover_with_months(self):
        resolved = await nl_query_service.resolve_metric("最近 3 个月离职率如何")
        assert resolved.definition.metric == "turnover_rate"
        assert resolved.params == {"months": 3}

    @pytest.mark.asyncio
    async def test_months_clamped(self):
        resolved = await nl_query_service.resolve_metric("近 99 个月离职率")
        assert resolved.params == {"months": 12}


class TestLlmResolve:
    """关键词未命中走 LLM JSON 映射"""

    @pytest.mark.asyncio
    async def test_llm_maps_to_whitelist(self):
        TenantContext.set_tenant_id("t-1")
        with patch(
            "hr.services.nl_query_service.llm_chat",
            new=AsyncMock(return_value='{"domain": "recruiting", "metric": "funnel"}'),
        ):
            resolved = await nl_query_service.resolve_metric("近期招人情况如何")
        assert resolved is not None
        assert resolved.source == "llm"
        assert resolved.definition.metric == "funnel"

    @pytest.mark.asyncio
    async def test_llm_outside_whitelist_rejected(self):
        TenantContext.set_tenant_id("t-1")
        with patch(
            "hr.services.nl_query_service.llm_chat",
            new=AsyncMock(return_value='{"domain": "personnel", "metric": "salary_raw"}'),
        ):
            resolved = await nl_query_service.resolve_metric("每个人的工资是多少")
        assert resolved is None

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self):
        TenantContext.set_tenant_id("t-1")
        with patch(
            "hr.services.nl_query_service.llm_chat",
            new=AsyncMock(side_effect=RuntimeError("llm down")),
        ):
            resolved = await nl_query_service.resolve_metric("随便问点什么")
        assert resolved is None


class TestAskWhitelist:
    """白名单越界拒绝"""

    @pytest.mark.asyncio
    async def test_out_of_scope_rejected(self):
        with patch(
            "hr.services.nl_query_service.llm_chat",
            new=AsyncMock(side_effect=RuntimeError("llm down")),
        ):
            with pytest.raises(BadRequestError, match="不在支持的指标范围"):
                await nl_query_service.ask(_mock_session(), "今天天气怎么样")

    @pytest.mark.asyncio
    async def test_empty_question_rejected(self):
        with pytest.raises(BadRequestError, match="问题不能为空"):
            await nl_query_service.ask(_mock_session(), "  ")


class TestAskFetch:
    """命中指标取数与回答"""

    @pytest.mark.asyncio
    async def test_turnover_fetch_and_answer(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session()
        turnover = TurnoverResponse(
            points=[TurnoverPoint(month="2026-09", offboarded=1, avg_headcount=100, rate=1.0)]
        )
        with (
            patch(
                "hr.services.report_service.report_service.get_turnover",
                new=AsyncMock(return_value=turnover),
            ) as mock_get,
            patch(
                "hr.services.nl_query_service.llm_chat",
                new=AsyncMock(return_value="近月离职率 1.0%（口径：当月离职人数/平均在编）。"),
            ),
        ):
            result = await nl_query_service.ask(session, "近 3 月离职率")
        mock_get.assert_awaited_once_with(session, months=3)
        assert result["metric"] == "离职率"
        assert result["data"]["points"][0]["rate"] == 1.0
        assert "1.0%" in result["answer"]
        assert result["metric_ref"]

    @pytest.mark.asyncio
    async def test_salary_without_permission_skips(self):
        result = await nl_query_service.ask(
            _mock_session(), "薪酬分布情况", can_salary=False
        )
        assert result["data"] is None
        assert "hr:salary_package:read" in result["answer"]
        assert result["metric"] == "薪酬分布"

    @pytest.mark.asyncio
    async def test_narration_failure_falls_back_template(self):
        TenantContext.set_tenant_id("t-1")
        turnover = TurnoverResponse(points=[])
        with (
            patch(
                "hr.services.report_service.report_service.get_turnover",
                new=AsyncMock(return_value=turnover),
            ),
            patch(
                "hr.services.nl_query_service.llm_chat",
                new=AsyncMock(side_effect=RuntimeError("llm down")),
            ),
        ):
            result = await nl_query_service.ask(_mock_session(), "离职率")
        assert "离职率" in result["answer"]
        assert result["data"] == {"points": []}
