"""hr_system 本体应用预置集成测试：工作区全量预置 / 幂等重跑 / Fuseki 缺席容错。

真库直跑（ontology + hr schema），整用例不 commit（session 关闭回滚，零清理负担）；
工作区图服务（model/mapping/rule/individual/concept 五单例）经 get_fuseki_client
注入内存 StubFuseki（解析 INSERT DATA 资源行，回答各服务 list/exists 查询），
不依赖真实 Fuseki；应用行（纯 PG）落 om_ontology_application。
"""

import re
from datetime import date
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from framework.tenant.context import TenantContext
from hr.models import Employee, Position

pytestmark = pytest.mark.integration

TENANT = "itest-hr-app"
APPLICATION = "hr_system"

# 预置内容规格（与 hr/services/ontology_provision_service.py 常量对拍）
EXPECTED_CLASSES = 16
EXPECTED_PROPERTIES = 38
EXPECTED_MAPPINGS = 36
EXPECTED_RULES = 3
EXPECTED_SKOS_TERMS = 6

_WORKSPACE_MODULES = (
    "ontology.services.workspace.model_service",
    "ontology.services.workspace.mapping_service",
    "ontology.services.workspace.rule_service",
    "ontology.services.workspace.individual_service",
    "ontology.services.workspace.concept_service",
)


def _binding(**fields: Any) -> dict:
    return {key: {"value": str(value)} for key, value in fields.items() if value is not None}


class _StubFuseki:
    """内存工作区图桩：update 解析 INSERT DATA/DELETE WHERE 资源行入库，
    query 回答 model/mapping/rule 列表查询与 individual 存在性查询（绑定形状
    对齐各服务 _aggregate/_row_to_item 读取的变量名）"""

    def __init__(self) -> None:
        self._resources: dict[str, dict[str, dict]] = {}  # graph → uri → 属性快照
        self.updates: list[str] = []

    def counts(self, kind: str) -> int:
        return sum(1 for res in self._resources.values() for r in res.values() if r["kind"] == kind)

    def names(self, kind: str) -> set[str]:
        return {
            r["name"]
            for res in self._resources.values()
            for r in res.values()
            if r["kind"] == kind and r.get("name")
        }

    def content_of(self, name: str) -> str:
        for res in self._resources.values():
            for r in res.values():
                if r["kind"] == "RULE" and r.get("name") == name:
                    return r.get("content") or ""
        return ""

    async def update(self, sparql: str) -> None:
        self.updates.append(sparql)
        graph_match = re.search(r"GRAPH\s*<([^>]+)>", sparql)
        if not graph_match:
            return
        graph = graph_match.group(1)
        if sparql.lstrip().startswith("DELETE WHERE"):
            # 主体取 GRAPH <g> { 后首个 <uri>（graph 自身 URI 不算）
            uri_match = re.search(r"GRAPH\s*<[^>]+>\s*\{\s*<([^>]+)>", sparql)
            if uri_match:
                self._resources.get(graph, {}).pop(uri_match.group(1), None)
            return
        if "INSERT DATA" not in sparql:
            return
        subject_match = re.search(r"GRAPH\s*<[^>]+>\s*\{\s*<([^>]+)>", sparql)
        kind_match = re.search(r'om:workspaceKind "([^"]+)"', sparql)
        if not (subject_match and kind_match):
            return
        record: dict[str, Any] = {"kind": kind_match.group(1)}
        for field, pattern in (
            ("id", r'om:workspaceId "([^"]+)"'),
            ("name", r'om:name "([^"]+)"'),
            ("label", r'rdfs:label "((?:[^"\\]|\\.)*)"'),
            ("propertyType", r'om:propertyType "([^"]+)"'),
            ("sourceField", r'om:sourceField "((?:[^"\\]|\\.)*)"'),
            ("status", r'om:status "([^"]+)"'),
            ("version", r"om:version (\d+)"),
            ("updatedAt", r'om:updatedAt "([^"]+)"'),
            ("language", r'om:language "([^"]+)"'),
            ("description", r'om:description "((?:[^"\\]|\\.)*)"'),
            ("content", r'om:content "((?:[^"\\]|\\.)*)"'),
            ("targetProperty", r"om:targetProperty <([^>]+)>"),
        ):
            match = re.search(pattern, sparql)
            if match:
                record[field] = match.group(1).replace('\\"', '"')
        self._resources.setdefault(graph, {})[subject_match.group(1)] = record

    async def query(self, sparql: str) -> dict[str, Any]:
        graph_match = re.search(r"GRAPH <([^>]+)>", sparql)
        store = self._resources.get(graph_match.group(1), {}) if graph_match else {}
        # individual 存在性：显式主体 <uri> om:workspaceId ?id
        subject_match = re.search(r"\{\s*<([^>]+)> om:workspaceId", sparql)
        if subject_match:
            exists = subject_match.group(1) in store
            bindings = [{"res": {"value": subject_match.group(1)}}] if exists else []
            return {"results": {"bindings": bindings}}
        if 'om:workspaceKind "CLASS"' in sparql:
            return {"results": {"bindings": [
                _binding(res=uri, id=r.get("id"), name=r.get("name"),
                         label=r.get("label"), version=r.get("version"))
                for uri, r in store.items() if r["kind"] == "CLASS"
            ]}}
        if 'om:workspaceKind "PROPERTY"' in sparql:
            return {"results": {"bindings": [
                _binding(res=uri, id=r.get("id"), name=r.get("name"),
                         label=r.get("label"), version=r.get("version"),
                         propertyType=r.get("propertyType"))
                for uri, r in store.items() if r["kind"] == "PROPERTY"
            ]}}
        if 'om:workspaceKind "MAPPING"' in sparql:
            return {"results": {"bindings": [
                _binding(res=uri, id=r.get("id"), field=r.get("sourceField"),
                         property=r.get("targetProperty"), status=r.get("status"),
                         version=r.get("version"), updatedAt=r.get("updatedAt"))
                for uri, r in store.items() if r["kind"] == "MAPPING"
            ]}}
        if 'om:workspaceKind "RULE"' in sparql:
            return {"results": {"bindings": [
                _binding(res=uri, id=r.get("id"), name=r.get("name"),
                         language=r.get("language"), status=r.get("status"),
                         version=r.get("version"), updatedAt=r.get("updatedAt"))
                for uri, r in store.items() if r["kind"] == "RULE"
            ]}}
        return {"results": {"bindings": []}}

    async def query_raw(self, sparql: str, accept: str) -> str:
        return ""


class _DownFuseki(_StubFuseki):
    """图存储不可用桩：所有 update/query 抛 httpx.ConnectError（网关翻译 503）"""

    async def update(self, sparql: str) -> None:
        raise httpx.ConnectError("connection refused")

    async def query(self, sparql: str) -> dict[str, Any]:
        raise httpx.ConnectError("connection refused")


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
def stub_fuseki(monkeypatch):
    import importlib

    stub = _StubFuseki()
    for module_path in _WORKSPACE_MODULES:
        module = importlib.import_module(module_path)
        monkeypatch.setattr(module, "get_fuseki_client", lambda _stub=stub: _stub)
    return stub


async def _cleanup(engine) -> None:
    async with AsyncSession(engine) as session:
        await session.execute(
            text(f"DELETE FROM ontology.om_ontology_application WHERE tenant_id = '{TENANT}'")
        )
        await session.commit()


@pytest.mark.asyncio
async def test_application_provision_full_workspace(engine, stub_fuseki):
    """全量预置：应用行 + 16 类/38 属性/SKOS 六概念/36 映射/实例/3 规则；
    重跑幂等零新建（类按 name、映射按 (sourceField,target)、规则按 name、实例按业务键）"""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add(
            Position(tenant_id=TENANT, code="ITEST-POS-01", name="探针岗位", headcount=3)
        )
        session.add(
            Employee(
                tenant_id=TENANT,
                employee_no="ITEST-E-001",
                name="探针员工",
                status="probation",
                job_level="P5",
                hire_date=date(2025, 6, 1),
            )
        )
        await session.flush()

        result = await _provision(session)
        assert result == {"application": APPLICATION}

        # 应用行落 PG（纯 PG savepoint，未提交行同 session 可见）
        rows = await session.execute(
            text(
                f"SELECT config FROM ontology.om_ontology_application "
                f"WHERE tenant_id = '{TENANT}' AND name = '{APPLICATION}'"
            )
        )
        config = rows.scalar_one()
        assert config["metadataSources"] == ["hr-pg"]
        assert config["linkedGlossaries"] == ["hr-domain"]
        assert sorted(config["productDomains"]) == [
            "Approval", "Attendance", "Compensation",
            "Performance", "Recruiting", "Workforce",
        ]

        # 工作区图计数对拍规格
        assert stub_fuseki.counts("CLASS") == EXPECTED_CLASSES
        assert stub_fuseki.counts("PROPERTY") == EXPECTED_PROPERTIES
        assert stub_fuseki.counts("MAPPING") == EXPECTED_MAPPINGS
        assert stub_fuseki.counts("RULE") == EXPECTED_RULES
        assert stub_fuseki.counts("CONCEPT") == EXPECTED_SKOS_TERMS
        # 实例：仅探针员工/岗位两行（其余类无业务数据跳过）
        assert stub_fuseki.counts("INDIVIDUAL") == 2

        # 类与属性命名对拍
        assert "Employee" in stub_fuseki.names("CLASS")
        assert "ActiveEmployee" in stub_fuseki.names("CLASS")
        assert "worksOnPosition" in stub_fuseki.names("PROPERTY")

        # 映射目标已存在（服务端校验通过即证）+ ACCEPTED 状态
        mapping_statuses = {
            r["status"]
            for res in stub_fuseki._resources.values()
            for r in res.values() if r["kind"] == "MAPPING"
        }
        assert mapping_statuses == {"ACCEPTED"}

        # 规则内容含真实类 URI 与实例谓词
        active = stub_fuseki.content_of("ActiveEmployeeRule")
        employee_uri = next(
            uri for uri, r in next(iter(stub_fuseki._resources.values())).items()
            if r["kind"] == "CLASS" and r["name"] == "Employee"
        )
        assert f"rdf:type <{employee_uri}>" in active
        assert "om:prop.employmentStatus" in active
        assert "BIND(IRI(?ref) AS ?e)" in stub_fuseki.content_of("HighPerformerRule")
        assert "SUBSTR(STR(NOW()), 1, 10)" in stub_fuseki.content_of("OpenLeaveRule")

        # 实例属性谓词对拍：员工个体带 om:prop.employeeNo 字面量
        employee_updates = [u for u in stub_fuseki.updates if "ITEST-E-001" in u]
        assert employee_updates and "om:prop.employeeNo" in employee_updates[0]

        # 重跑幂等：全命中跳过，图资源零新增
        before = len(stub_fuseki._resources[next(iter(stub_fuseki._resources))])
        assert await _provision(session) == {"application": APPLICATION}
        after = len(stub_fuseki._resources[next(iter(stub_fuseki._resources))])
        assert after == before, "重跑不应新增工作区资源"
        # 重跑实例走业务键幂等跳过（_exists 命中桩内已存个体）
        assert stub_fuseki.counts("INDIVIDUAL") == 2


async def _provision(session: AsyncSession):
    from hr.services.ontology_provision_service import provision_hr_ontology_application

    return await provision_hr_ontology_application(session)


@pytest.mark.asyncio
async def test_application_survives_fuseki_down(engine, monkeypatch):
    """Fuseki 不可用：工作区段 503 跳过（info 不抛），应用行（纯 PG）保留"""
    import importlib

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        for module_path in _WORKSPACE_MODULES:
            module = importlib.import_module(module_path)
            monkeypatch.setattr(module, "get_fuseki_client", lambda: _DownFuseki())

        result = await _provision(session)

        assert result is None
        rows = await session.execute(
            text(
                f"SELECT count(*) FROM ontology.om_ontology_application "
                f"WHERE tenant_id = '{TENANT}' AND name = '{APPLICATION}'"
            )
        )
        assert int(rows.scalar_one()) == 1, "应用行不应随工作区段回滚"


@pytest.mark.asyncio
async def test_application_skips_when_ontology_absent(engine):
    """ontology 缺席：应用段整体跳过返回 None，零残留"""

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
            assert await _provision(session) is None
        rows = await session.execute(
            text(
                f"SELECT count(*) FROM ontology.om_ontology_application "
                f"WHERE tenant_id = '{TENANT}'"
            )
        )
        assert int(rows.scalar_one()) == 0
