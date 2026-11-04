"""报表快照任务集成测试（§7 批 G.1）：四域快照落 Redis key。

真库直算 + 真 Redis 落盘；任务入口的锁/任务会话/ontology 补偿经 stub 隔离
（锁与补偿各有独立测试），验证四域 key 齐全、载荷结构与 TTL 口径。
"""

import json
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from framework.tenant.context import TenantContext
from hr.models import Employee
from hr.services.report_service import (
    SNAPSHOT_KEY_PREFIX,
    SNAPSHOT_TTL_SECONDS,
)
from hr.tasks.services import report_snapshot_task

pytestmark = pytest.mark.integration

TENANT = "itest-hr-snapshot"

SNAPSHOT_DOMAINS = ("personnel", "recruiting", "compensation", "performance")


@pytest_asyncio.fixture()
async def session(postgres_engine, redis_client) -> AsyncIterator[AsyncSession]:
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
                employee_no="ITEST-S-001",
                name="快照探针员工",
                status="regular",
                hire_date=date.today() - timedelta(days=100),
            )
        )
        await sess.flush()
        yield sess
        await sess.rollback()
    TenantContext.clear()

    for domain in SNAPSHOT_DOMAINS:
        await redis_client.delete(f"{SNAPSHOT_KEY_PREFIX}{domain}")


@pytest.fixture(autouse=True)
def _stub_task_env(monkeypatch, session):
    """锁改为直接放行、任务会话绑定测试 session、屏蔽 ontology 补偿（独立测试覆盖）"""

    class _Lock:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return False

    class _LockProvider:
        def acquire_context(self, *args, **kwargs):
            return _Lock()

    @asynccontextmanager
    async def _task_session():
        yield session

    async def _noop_compensate(session, tenant_id):
        return None

    monkeypatch.setattr(report_snapshot_task, "get_lock_provider", lambda *_: _LockProvider())
    monkeypatch.setattr(report_snapshot_task, "get_task_session", _task_session)
    monkeypatch.setattr(report_snapshot_task, "_compensate_ontology_provision", _noop_compensate)


@pytest.mark.asyncio
async def test_snapshot_writes_four_domain_keys(session):
    """任务跑完四域 key 齐全：personnel/recruiting/compensation/performance，TTL 25h"""
    await report_snapshot_task.run_report_snapshot_task()

    payloads: dict[str, dict] = {}
    for domain in SNAPSHOT_DOMAINS:
        raw = await report_snapshot_task.RedisUtil.get(f"{SNAPSHOT_KEY_PREFIX}{domain}")
        assert raw is not None, f"快照 key 缺失: {domain}"
        payloads[domain] = json.loads(raw)

    personnel = payloads["personnel"]
    assert "headcount_trend" in personnel and "turnover" in personnel
    assert personnel["computed_at"] == date.today().isoformat()
    trend = personnel["headcount_trend"]
    assert len(trend) == report_snapshot_task.SNAPSHOT_MONTHS
    assert trend[-1]["count"] >= 1

    for domain in ("recruiting", "compensation", "performance"):
        assert payloads[domain], f"{domain} 快照载荷为空"


@pytest.mark.asyncio
async def test_snapshot_rerun_overwrites_idempotent(session):
    """重复执行覆盖写不报错（幂等覆盖语义），key 数量恒定"""
    await report_snapshot_task.run_report_snapshot_task()
    first = await report_snapshot_task.RedisUtil.get(f"{SNAPSHOT_KEY_PREFIX}personnel")
    await report_snapshot_task.run_report_snapshot_task()
    second = await report_snapshot_task.RedisUtil.get(f"{SNAPSHOT_KEY_PREFIX}personnel")

    assert json.loads(first) == json.loads(second)
    ttl = await report_snapshot_task.RedisUtil.get_client().ttl(
        f"{SNAPSHOT_KEY_PREFIX}personnel"
    )
    assert 0 < ttl <= SNAPSHOT_TTL_SECONDS
