"""NL 问数服务单元测试

覆盖：关键词规则命中（含月数抽取）、白名单越界 400、llm JSON 映射（解析失败
不猜指标）、薪酬域无权限跳过并在回答注明、LLM 回答失败降级模板文案。
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.clients.ontology_client import OntologyUnavailableError
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


class TestAssetMetricRouting:
    """appliedTo 资产→指标路由：问数附挂接治理指标上下文"""

    @staticmethod
    def _client_stub(metrics_by_table):
        async def fake_get_asset_metrics(session, *, tenant_id, collection, ref):
            metrics = metrics_by_table.get(ref)
            if metrics is None:
                return {"asset": {}, "metricCount": 0, "metrics": []}
            return {"asset": {}, "metricCount": len(metrics), "metrics": metrics}

        return SimpleNamespace(get_asset_metrics=AsyncMock(side_effect=fake_get_asset_metrics))

    @pytest.mark.asyncio
    async def test_answer_carries_attached_governance_metrics(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session()
        turnover = TurnoverResponse(
            points=[TurnoverPoint(month="2026-09", offboarded=1, avg_headcount=100, rate=1.0)]
        )
        metrics = {
            "hr-pg.ai_platform.hr.employees": [
                {"id": "m1", "type": "metric", "name": "workforce_headcount",
                 "fullyQualifiedName": "workforce_headcount", "displayName": "在编人数"}
            ],
            "hr-pg.ai_platform.hr.employee_changes": [
                {"id": "m2", "type": "metric", "name": "attrition_rate",
                 "fullyQualifiedName": "attrition_rate", "displayName": "离职率"}
            ],
        }
        client_stub = self._client_stub(metrics)
        with (
            patch(
                "hr.services.report_service.report_service.get_turnover",
                new=AsyncMock(return_value=turnover),
            ),
            patch(
                "framework.clients.ontology_client.get_ontology_client",
                return_value=client_stub,
            ),
            patch(
                "hr.services.nl_query_service.llm_chat",
                new=AsyncMock(return_value="近月离职率 1.0%。"),
            ) as mock_llm,
        ):
            result = await nl_query_service.ask(session, "近 3 月离职率")
        assert result["asset_metrics"] == ["在编人数", "离职率"]
        # 两表各反查一次
        assert client_stub.get_asset_metrics.await_count == 2
        user_content = mock_llm.call_args.args[1][1]["content"]
        assert "治理指标" in user_content and "在编人数" in user_content

    @pytest.mark.asyncio
    async def test_duplicate_metrics_deduped(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session()
        turnover = TurnoverResponse(points=[])
        same_metric = [
            {"id": "m1", "type": "metric", "name": "workforce_headcount",
             "fullyQualifiedName": "workforce_headcount", "displayName": "在编人数"}
        ]
        client_stub = self._client_stub(
            {
                "hr-pg.ai_platform.hr.employees": same_metric,
                "hr-pg.ai_platform.hr.employee_changes": same_metric,
            }
        )
        with (
            patch(
                "hr.services.report_service.report_service.get_turnover",
                new=AsyncMock(return_value=turnover),
            ),
            patch(
                "framework.clients.ontology_client.get_ontology_client",
                return_value=client_stub,
            ),
            patch(
                "hr.services.nl_query_service.llm_chat",
                new=AsyncMock(side_effect=RuntimeError("llm down")),
            ),
        ):
            result = await nl_query_service.ask(session, "离职率")
        assert result["asset_metrics"] == ["在编人数"]

    @pytest.mark.asyncio
    async def test_ontology_unavailable_keeps_answer(self):
        """ontology 缺席/不可用 → 空上下文，问数主链不受影响"""
        TenantContext.set_tenant_id("t-1")
        session = _mock_session()
        turnover = TurnoverResponse(
            points=[TurnoverPoint(month="2026-09", offboarded=1, avg_headcount=100, rate=1.0)]
        )
        client_stub = SimpleNamespace(
            get_asset_metrics=AsyncMock(
                side_effect=OntologyUnavailableError("ontology down")
            )
        )
        with (
            patch(
                "hr.services.report_service.report_service.get_turnover",
                new=AsyncMock(return_value=turnover),
            ),
            patch(
                "framework.clients.ontology_client.get_ontology_client",
                return_value=client_stub,
            ),
            patch(
                "hr.services.nl_query_service.llm_chat",
                new=AsyncMock(return_value="近月离职率 1.0%。"),
            ),
        ):
            result = await nl_query_service.ask(session, "近 3 月离职率")
        assert result["asset_metrics"] == []
        assert "1.0%" in result["answer"]

    @pytest.mark.asyncio
    async def test_reverse_lookup_failure_skips_table(self):
        """单表反查抛未知异常 → 跳过该表，不影响其余资产上下文"""
        TenantContext.set_tenant_id("t-1")
        session = _mock_session()
        turnover = TurnoverResponse(points=[])
        metrics = {
            "hr-pg.ai_platform.hr.employees": [
                {"id": "m1", "type": "metric", "name": "workforce_headcount",
                 "fullyQualifiedName": "workforce_headcount", "displayName": "在编人数"}
            ],
        }
        client_stub = self._client_stub(metrics)
        original = client_stub.get_asset_metrics.side_effect

        async def flaky(session, *, tenant_id, collection, ref):
            if ref == "hr-pg.ai_platform.hr.employee_changes":
                raise RuntimeError("db glitch")
            return await original(session, tenant_id=tenant_id, collection=collection, ref=ref)

        client_stub.get_asset_metrics.side_effect = flaky
        with (
            patch(
                "hr.services.report_service.report_service.get_turnover",
                new=AsyncMock(return_value=turnover),
            ),
            patch(
                "framework.clients.ontology_client.get_ontology_client",
                return_value=client_stub,
            ),
            patch(
                "hr.services.nl_query_service.llm_chat",
                new=AsyncMock(side_effect=RuntimeError("llm down")),
            ),
        ):
            result = await nl_query_service.ask(session, "离职率")
        assert result["asset_metrics"] == ["在编人数"]
