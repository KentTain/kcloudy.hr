"""ontology 资产注册管线集成测试（§7 批 E.4）：注册幂等重跑 / 缺失补偿。

真库直跑（ontology schema），整用例不 commit（session 关闭回滚，零清理负担）；
ontology 实体创建的事件发布与任务投递经 fixture 屏蔽，不依赖任务存储。
"""

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from framework.tenant.context import TenantContext
from hr.services.ontology_provision_service import provision_hr_assets

pytestmark = pytest.mark.integration

TENANT = "itest-hr-ontology"

# 管线写入的 ontology 表（version 表先于主表清理顺序无依赖，均按租户直删）
_PROVISION_TABLES = (
    "entity_relation",
    "metric_entity_version",
    "metric_entity",
    "om_custom_unit",
    "glossary_term_entity_version",
    "glossary_term_entity",
    "glossary_entity_version",
    "glossary_entity",
    "data_product_entity_version",
    "data_product_entity",
    "classification_entity_version",
    "classification_entity",
    "domain_entity_version",
    "domain_entity",
    "table_entity_version",
    "table_entity",
    "database_schema_entity_version",
    "database_schema_entity",
    "database_entity_version",
    "database_entity",
    "service_entity_version",
    "service_entity",
)


@pytest_asyncio.fixture()
async def engine(postgres_engine):
    from framework.database.events.tenant import register_tenant_events
    from framework.database.interceptors.query import register_tenant_auto_filter

    register_tenant_auto_filter()
    register_tenant_events()
    await _cleanup(postgres_engine)
    yield postgres_engine
    await _cleanup(postgres_engine)


@pytest.fixture(autouse=True)
def _tenant():
    TenantContext.set_tenant_id(TENANT)
    yield
    TenantContext.clear()


@pytest.fixture(autouse=True)
def _mute_side_effects(monkeypatch):
    """屏蔽实体创建伴生的事件发布与向量/图谱任务投递（集成环境不消费）；
    iam client 替身化（owner 解析返回固定用户，不触真实 iam 库数据）"""
    from ontology.listeners.services.queue import graph_projection_consumer
    from ontology.services.entity import entity_repository as er
    from ontology.services.search import embedding_service

    class _Stub:
        async def publish(self, *args, **kwargs):
            return None

    async def _noop(*args, **kwargs):
        return None

    class _FakeIam:
        async def list_role_user_ids(self, session, tenant_id, role_code):
            return ["user-owner-1"]

        async def get_users_batch(self, session, user_ids):
            from types import SimpleNamespace

            return [SimpleNamespace(id="user-owner-1", username="hradmin", nickname="HR 管理员")]

    monkeypatch.setattr(er, "event_publisher", _Stub())
    monkeypatch.setattr(embedding_service, "submit_embedding_task", _noop)
    monkeypatch.setattr(graph_projection_consumer, "submit_graph_projection_task", _noop)
    from framework.clients import iam_client as iam_module

    monkeypatch.setattr(iam_module, "get_iam_client", lambda: _FakeIam())


async def _cleanup(engine) -> None:
    async with AsyncSession(engine) as session:
        for table in _PROVISION_TABLES:
            await session.execute(
                text(f"DELETE FROM ontology.{table} WHERE tenant_id = '{TENANT}'")
            )
        await session.commit()


async def _count(engine, table: str) -> int:
    async with AsyncSession(engine) as session:
        rows = await session.execute(
            text(
                f"SELECT count(*) FROM ontology.{table} "
                f"WHERE tenant_id = '{TENANT}'"
            )
        )
        return int(rows.scalar_one())


async def _scalar(session, sql: str) -> int:
    rows = await session.execute(text(sql))
    return int(rows.scalar_one())


@pytest.mark.asyncio
async def test_provision_creates_and_rerun_idempotent(engine):
    """首跑全量注册（29 表/7 域/数据产品/术语/指标 + 56 实体挂分类）；
    同事务重跑全命中零新建；回滚零残留"""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    tenant_filter = f"tenant_id = '{TENANT}'"
    async with maker() as session:
        first = await provision_hr_assets(session)
        assert first == {
            "classifications": 1, "tables": 29, "domains": 7,
            "dataProducts": 1, "terms": 3, "metrics": 16,
        }
        await session.flush()

        # 批 C 落库核验（同事务 SQL 直查为权威证据，未提交行同 session 可见）
        assert (
            await _scalar(
                session,
                f"SELECT count(*) FROM ontology.entity_relation WHERE {tenant_filter} "
                "AND relation = 'tagOf'",
            )
            == 56
        ), "56 实体 tagOf 边未落库"
        assert (
            await _scalar(
                session,
                f"SELECT count(*) FROM ontology.table_entity WHERE {tenant_filter} "
                "AND jsonb_array_length(payload->'terms') > 0",
            )
            == 14
        ), "三域 14 表 terms 引用未落库"
        assert (
            await _scalar(
                session,
                f"SELECT count(*) FROM ontology.glossary_term_entity WHERE {tenant_filter} "
                "AND payload->>'displayName' = name AND payload->'synonyms' = '[]'::jsonb",
            )
            == 3
        ), "术语 displayName/synonyms 未落库"
        assert (
            await _scalar(
                session,
                f"SELECT count(*) FROM ontology.domain_entity WHERE {tenant_filter} "
                "AND payload->'owner'->>'id' = 'user-owner-1'",
            )
            == 7
        ), "主域+6 子域 owner 引用未落库"
        assert (
            await _scalar(
                session,
                f"SELECT count(*) FROM ontology.data_product_entity WHERE {tenant_filter} "
                "AND fully_qualified_name = 'HR.hr_core_assets' "
                "AND payload->'domain'->>'fullyQualifiedName' = 'HR' "
                "AND payload->'owner'->>'id' = 'user-owner-1'",
            )
            == 1
        ), "数据产品行/域引用/owner 未落库"

        # 事务内重跑：同 session 可见未提交行，全部命中既有 FQN
        second = await provision_hr_assets(session)
        assert second == {
            "classifications": 0, "tables": 0, "domains": 0,
            "dataProducts": 0, "terms": 0, "metrics": 0,
        }
        # 会话关闭即回滚，无 commit
    assert await _count(engine, "table_entity") == 0
    assert await _count(engine, "metric_entity") == 0
    assert await _count(engine, "domain_entity") == 0
    assert await _count(engine, "data_product_entity") == 0
    assert await _count(engine, "classification_entity") == 0


@pytest.mark.asyncio
async def test_provision_compensates_missing_entities(engine):
    """人工删除部分资产后重跑仅补缺失（快照任务幂等补偿语义）"""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await provision_hr_assets(session)
        await session.execute(
            text(
                f"DELETE FROM ontology.table_entity WHERE tenant_id = '{TENANT}' "
                f"AND fully_qualified_name = 'hr-pg.ai_platform.hr.payroll_entries'"
            )
        )
        await session.execute(
            text(
                f"DELETE FROM ontology.metric_entity WHERE tenant_id = '{TENANT}' "
                f"AND fully_qualified_name = 'headcount_gap'"
            )
        )
        await session.flush()

        patched = await provision_hr_assets(session)
        assert patched["tables"] == 1
        assert patched["metrics"] == 1
        assert patched["domains"] == 0
        assert patched["dataProducts"] == 0


@pytest.mark.asyncio
async def test_provision_backfills_nested_parent_for_existing_domains(engine):
    """存量旧形态顶层域（验收 2）：重跑仅 patch 补挂 parent，FQN 列保持裸名"""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await provision_hr_assets(session)
        await session.execute(
            text(
                f"UPDATE ontology.domain_entity SET "
                f"fully_qualified_name = split_part(fully_qualified_name, '.', 2), "
                f"payload = payload - 'parent' "
                f"WHERE tenant_id = '{TENANT}' "
                f"AND fully_qualified_name LIKE 'HR.%'"
            )
        )
        await session.flush()

        patched = await provision_hr_assets(session)
        assert patched["domains"] == 0, "存量域不应新建"

        rows = await session.execute(
            text(
                f"SELECT fully_qualified_name, payload->'parent' FROM ontology.domain_entity "
                f"WHERE tenant_id = '{TENANT}' AND name != 'HR' "
                f"AND payload->>'domainType' = 'Aggregate' "
                f"AND fully_qualified_name NOT LIKE 'HR.%'"
            )
        )
        domains = {fqn: parent for fqn, parent in rows}
        assert set(domains) == {
            "Recruiting", "Compensation", "Performance",
            "Workforce", "Attendance", "Approval",
        }, "存量子域 FQN 列应保持旧顶层裸名（patch 不重算）"
        assert all(parent is not None for parent in domains.values()), "payload parent 未补挂"


@pytest.mark.asyncio
async def test_provision_skips_when_ontology_absent(engine):
    """ontology 缺席（验收 4）：整体跳过返回 None，真库零写入"""

    class _DeadClient:
        def __getattr__(self, name):
            from framework.clients.ontology_client import OntologyUnavailableError

            async def _raise(*args, **kwargs):
                raise OntologyUnavailableError("ontology 模块不可用")

            return _raise

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        from unittest.mock import patch

        with patch(
            "framework.clients.ontology_client.get_ontology_client",
            return_value=_DeadClient(),
        ):
            result = await provision_hr_assets(session)

    assert result is None
    assert await _count(engine, "domain_entity") == 0
    assert await _count(engine, "data_product_entity") == 0
    assert await _count(engine, "table_entity") == 0
