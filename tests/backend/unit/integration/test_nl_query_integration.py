"""NL 问数集成测试（§7 批 G.1）：白名单指标映射 → 真库聚合取数 → 回答。

真库直跑（hr schema），指标映射与回答生成的 llm_chat 经 stub 固定输出
（LLM 通道另有单元测试覆盖），验证关键词/LLM 两路映射、真库取数与越界拒绝。
"""

from datetime import date, timedelta
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from framework.common.exceptions import BadRequestError
from framework.tenant.context import TenantContext
from hr.models import Employee
from hr.services.nl_query_service import nl_query_service

pytestmark = pytest.mark.integration

TENANT = "itest-hr-nl"


@pytest_asyncio.fixture()
async def session(postgres_engine) -> AsyncIterator[AsyncSession]:
    from framework.database.events.tenant import register_tenant_events
    from framework.database.interceptors.query import register_tenant_auto_filter

    register_tenant_auto_filter()
    register_tenant_events()
    TenantContext.set_tenant_id(TENANT)
    maker = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with maker() as sess:
        sess.add(
            Employee(
                tenant_id=TENANT,
                employee_no="ITEST-NL-001",
                name="问数探针员工",
                status="regular",
                hire_date=date.today() - timedelta(days=200),
            )
        )
        await sess.flush()
        yield sess
        await sess.rollback()
    TenantContext.clear()


@pytest.fixture(autouse=True)
def _stub_llm(monkeypatch):
    """固定 llm_chat 输出：映射调用返回 {}（走不到白名单），回答调用返回固定文案"""

    async def _fake_llm_chat(tenant_id, messages, **kwargs):
        system = messages[0]["content"] if messages else ""
        if "指标映射器" in system:
            return "{}"
        return "根据报表数据，在编人数为 1 人。口径：在编含试用与正式。"

    monkeypatch.setattr("hr.services.nl_query_service.llm_chat", _fake_llm_chat)


@pytest.mark.asyncio
async def test_ask_headcount_keyword_hit(session: AsyncSession):
    """关键词命中在编人数：真库取数 active_count≥1，回答走 stub 文案"""
    result = await nl_query_service.ask(session, "现在在编有多少人")

    assert result["metric"] == "在编人数"
    assert result["domain"] == "personnel"
    assert result["source"] == "keyword"
    assert result["data"]["cards"]["active_count"] >= 1
    assert "在编人数" in result["answer"]
    assert result["metric_ref"]


@pytest.mark.asyncio
async def test_ask_turnover_with_months(session: AsyncSession):
    """「近 N 月」参数抽取：离职率取数返回 N 个点"""
    result = await nl_query_service.ask(session, "近 3 个月离职率怎么样")

    assert result["metric"] == "离职率"
    assert len(result["data"]["points"]) == 3


@pytest.mark.asyncio
async def test_ask_llm_maps_into_whitelist(monkeypatch, session: AsyncSession):
    """关键词未命中时 LLM 映射进白名单：source=llm，绩效分布真库取数"""

    async def _map_perf(tenant_id, messages, **kwargs):
        system = messages[0]["content"] if messages else ""
        if "指标映射器" in system:
            return '{"domain": "performance", "metric": "perf_summary"}'
        return "绩效分布数据如下。"

    monkeypatch.setattr("hr.services.nl_query_service.llm_chat", _map_perf)
    result = await nl_query_service.ask(session, "各职级每月收入概况怎么样")

    assert result["metric"] == "绩效分布"
    assert result["source"] == "llm"
    assert isinstance(result["data"]["cycles"], list)


@pytest.mark.asyncio
async def test_ask_outside_whitelist_rejected(session: AsyncSession):
    """关键词与 LLM 映射均未命中：400 拒绝，不猜指标"""
    with pytest.raises(BadRequestError, match="不在支持的指标范围"):
        await nl_query_service.ask(session, "今天天气怎么样")
