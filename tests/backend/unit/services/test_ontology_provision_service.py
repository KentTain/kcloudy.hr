"""ontology 资产注册管线单元测试

覆盖：全量新建（1 分类/29 表带术语/7 域带 owner+挂载/数据产品/术语表+3 术语
带 displayName+synonyms/6 单位/16 指标 + 56 实体挂分类）、既有 FQN 全命中
零新建（幂等 + 存量域补挂 parent + 存量表补 terms + 存量术语补 displayName/
synonyms）、存量服务缺连接配置补写（patch /connection）、owner iam 降级省略
（无用户/异常）、ontology 不可用返回 None。替身打在 framework 客户端边界
（hr 唯一依赖面），不触 ontology 内部。
"""

from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import pytest

from framework.clients.ontology_client import OntologyUnavailableError
from framework.tenant.context import TenantContext
from hr.services.ontology_provision_service import provision_hr_assets

pytestmark = pytest.mark.asyncio

_TABLES = (
    "employees",
    "positions",
    "employee_changes",
    "employee_contracts",
    "employee_attachments",
    "employee_field_groups",
    "employee_field_definitions",
    "employee_attribute_values",
    "job_requisitions",
    "job_postings",
    "candidates",
    "candidate_applications",
    "offers",
    "interviews",
    "salary_items",
    "salary_bands",
    "employee_salary_packages",
    "payroll_runs",
    "payroll_entries",
    "perf_cycles",
    "perf_goals",
    "perf_reviews",
    "attendance_records",
    "attendance_import_batches",
    "leave_types",
    "leave_balances",
    "leave_requests",
    "approval_requests",
    "approval_actions",
)
_DOMAIN_NAMES = (
    "Recruiting",
    "Compensation",
    "Performance",
    "Workforce",
    "Attendance",
    "Approval",
)
# 子域 displayName 中文化对齐表（与 hr-open 包域根术语逐字一致）
_DOMAIN_DISPLAY = {
    "Recruiting": "招聘",
    "Compensation": "薪酬",
    "Performance": "绩效",
    "Workforce": "员工与组织",
    "Attendance": "考勤",
    "Approval": "审批",
}
_METRIC_NAMES = (
    "attrition_rate",
    "headcount_gap",
    "perf_rating_distribution",
    "workforce_headcount",
    "workforce_transfer_rate",
    "recruiting_time_to_hire",
    "recruiting_offer_acceptance_rate",
    "recruiting_funnel_conversion_rate",
    "comp_payroll_total",
    "comp_payroll_per_capita",
    "comp_band_compa_ratio",
    "perf_goal_completion_rate",
    "perf_high_rating_ratio",
    "attendance_absence_rate",
    "attendance_overtime_total",
    "leave_usage_rate",
)

# 既有资产全集：(spec_key, fqn)——幂等用例据此命中
_EXISTING_SPECS = (
    [
        ("classification", "HR人力资源类"),
        ("domain", "HR"),
        ("dataProduct", "HR.hr_core_assets"),
    ]
    + [("databaseService", "hr-pg"), ("database", "hr-pg.ai_platform")]
    + [("databaseSchema", "hr-pg.ai_platform.hr")]
    + [("table", f"hr-pg.ai_platform.hr.{t}") for t in _TABLES]
    + [("domain", d) for d in _DOMAIN_NAMES]
    + [("glossary", "hr-domain")]
    + [("glossaryTerm", f"hr-domain.{t}") for t in ("招聘管理", "薪酬管理", "绩效管理")]
    + [("metric", m) for m in _METRIC_NAMES]
)

_FAKE_CONNECTION = {
    "config": {
        "type": "Postgres",
        "hostPort": "localhost:5432",
        "username": "tester",
        "password": "secret",
        "database": "ai_platform",
    }
}


class _FakeClient:
    """OntologyClient 替身：existing 按 (spec_key, fqn) 命中返回 OM dict，写操作记账"""

    def __init__(self):
        self.existing: dict[tuple[str, str], dict] = {}
        self.created: list[tuple[str, str]] = []
        self.domain_bodies: list[dict] = []
        self.product_bodies: list[dict] = []
        self.asset_bodies: list[dict] = []
        self.term_bodies: list[dict] = []
        self.patches: list[tuple[str, str, list]] = []
        self.bulks: list[tuple[str, list]] = []
        self.tag_applies: list[tuple[str, str, str]] = []

    @staticmethod
    def _om(spec_key: str, fqn: str, **extra) -> dict:
        return {"id": fqn, "name": fqn.rsplit(".", 1)[-1], "fullyQualifiedName": fqn, **extra}

    async def entity_get_by_fqn(self, session, *, tenant_id, spec_key, fqn):
        return self.existing.get((spec_key, fqn))

    async def entity_get_by_fqns(self, session, *, tenant_id, spec_key, fqns):
        return [
            self.existing[(spec_key, fqn)]
            for fqn in fqns
            if (spec_key, fqn) in self.existing
        ]

    async def entity_create(self, session, *, tenant_id, spec_key, name, payload):
        self.created.append((spec_key, name))
        return self._om(spec_key, name)

    async def entity_patch(self, session, *, tenant_id, spec_key, entity_id, ops):
        self.patches.append((spec_key, entity_id, ops))
        return {"id": entity_id}

    async def service_create(self, session, *, tenant_id, service_type, body):
        self.created.append((service_type, body["name"]))
        return self._om(service_type, body["name"])

    async def asset_create(self, session, *, tenant_id, asset_type, body):
        fqn = f'{body["parent"]}.{body["name"]}'
        self.created.append((asset_type, fqn))
        self.asset_bodies.append(body)
        return self._om(asset_type, fqn)

    async def domain_create(self, session, *, tenant_id, body):
        self.created.append(("domain", body["name"]))
        self.domain_bodies.append(body)
        return self._om("domain", body["name"])

    async def domain_bulk_add_assets(self, session, *, tenant_id, domain_name, assets):
        self.bulks.append((domain_name, assets))
        return {"added": len(assets)}

    async def data_product_create(self, session, *, tenant_id, body):
        self.created.append(("dataProduct", body["name"]))
        self.product_bodies.append(body)
        return self._om("dataProduct", f'{body["domain"]}.{body["name"]}')

    async def term_create(self, session, *, tenant_id, body):
        fqn = f'{body["glossary"]}.{body["name"]}'
        self.created.append(("glossaryTerm", fqn))
        self.term_bodies.append(body)
        return self._om("glossaryTerm", fqn)

    async def tag_apply(self, session, *, tenant_id, collection, entity_fqn, tag_fqn):
        self.tag_applies.append((collection, entity_fqn, tag_fqn))
        return self._om(collection, entity_fqn)

    async def unit_get(self, session, *, tenant_id, name):
        return self.existing.get(("unit", name))

    async def unit_create(self, session, *, tenant_id, body):
        self.created.append(("unit", body["name"]))
        return self._om("unit", body["name"])

    async def metric_create(self, session, *, tenant_id, body):
        self.created.append(("metric", body["name"]))
        return self._om("metric", body["name"])


class _DeadClient:
    """全方法上抛 OntologyUnavailableError（ontology 模块缺席/网关不可达）"""

    def __getattr__(self, name):
        async def _raise(*args, **kwargs):
            raise OntologyUnavailableError("ontology 模块不可用")

        return _raise


def _mock_session() -> MagicMock:
    session = MagicMock()

    @asynccontextmanager
    async def fake_nested():
        yield

    session.begin_nested = fake_nested
    return session


_OWNER_REF = {"id": "user-1", "type": "user", "displayName": "HR 管理员"}


class _FakeIam:
    """iam client 替身：owner 角色解析返回固定用户"""

    async def list_role_user_ids(self, session, tenant_id, role_code):
        assert role_code == f"{tenant_id}:owner"
        return ["user-1"]

    async def get_users_batch(self, session, user_ids):
        from types import SimpleNamespace

        return [SimpleNamespace(id="user-1", username="hradmin", nickname="HR 管理员")]


@pytest.fixture(autouse=True)
def _client_mocks():
    client = _FakeClient()
    TenantContext.set_tenant_id("tenant-1")
    with (
        patch(
            "framework.clients.ontology_client.get_ontology_client",
            return_value=client,
        ),
        patch(
            "framework.clients.iam_client.get_iam_client",
            return_value=_FakeIam(),
        ),
        patch(
            "hr.services.ontology_provision_service._connection_config_from_settings",
            return_value=None,
        ),
    ):
        yield client
    TenantContext.clear()


def _seed_existing(
    client: _FakeClient,
    *,
    service_connection: dict | None = None,
    domains_with_parent: bool = False,
    tables_with_terms: bool = False,
    terms_with_display: bool = False,
    domains_with_display: bool = False,
):
    for spec_key, fqn in _EXISTING_SPECS:
        extra = {}
        if spec_key == "databaseService" and service_connection is not None:
            extra["connection"] = service_connection
        if spec_key == "domain" and domains_with_parent:
            # 读面 OM 形态：payload 键展开到顶层（parent 存在 = 已子域化）
            extra["parent"] = {"fullyQualifiedName": "HR", "type": "domain"}
        if spec_key == "table" and tables_with_terms:
            extra["terms"] = [
                {
                    "id": fqn,
                    "type": "glossaryTerm",
                    "fullyQualifiedName": "hr-domain.招聘管理",
                    "displayName": "招聘管理",
                }
            ]
        if spec_key == "glossaryTerm" and terms_with_display:
            extra["displayName"] = fqn.rsplit(".", 1)[-1]
            extra["synonyms"] = []
        if spec_key == "domain" and domains_with_display and fqn in _DOMAIN_DISPLAY:
            extra["displayName"] = _DOMAIN_DISPLAY[fqn]
        client.existing[(spec_key, fqn)] = _FakeClient._om(spec_key, fqn, **extra)


async def test_provision_creates_full_asset_tree(_client_mocks):
    result = await provision_hr_assets(_mock_session())

    assert result == {
        "classifications": 1, "tables": 29, "domains": 7,
        "dataProducts": 1, "terms": 3, "metrics": 16,
    }

    def _created(kind: str) -> list[tuple[str, str]]:
        return [entry for entry in _client_mocks.created if entry[0] == kind]

    # 治理归类：1 分类 + 1 主域 + 6 子域（带 parent 新 FQN）+ 1 数据产品
    assert _created("classification") == [("classification", "HR人力资源类")]
    assert len(_client_mocks.domain_bodies) == 7
    root_body = _client_mocks.domain_bodies[0]
    assert root_body["name"] == "HR"
    assert root_body["domainType"] == "Aggregate"
    for body in _client_mocks.domain_bodies[1:]:
        assert body["parent"] == "HR"
        assert "parent" not in root_body
    # 步骤5：主域 + 子域 + 数据产品带 iam owner 引用
    assert root_body["owner"] == _OWNER_REF
    assert all(body["owner"] == _OWNER_REF for body in _client_mocks.domain_bodies[1:])
    assert len(_client_mocks.product_bodies) == 1
    product_body = _client_mocks.product_bodies[0]
    assert product_body["name"] == "hr_core_assets"
    assert product_body["domain"] == "HR"
    assert product_body["displayName"] == "HR 核心数据资产"
    assert product_body["owner"] == _OWNER_REF
    assert len(_created("databaseService")) == 1
    # 资产：1 库 + 1 schema + 29 表
    assert len(_created("database")) == 1
    assert len(_created("databaseSchema")) == 1
    assert len(_created("table")) == 29
    assert len(_created("glossary")) == 1
    assert len(_created("glossaryTerm")) == 3
    # 术语 body 带 displayName/synonyms（与 hr-open 包术语 payload 形态对齐）
    for body in _client_mocks.term_bodies:
        assert body["displayName"] == body["name"]
        assert body["synonyms"] == []
    assert len(_created("unit")) == 6
    assert len(_created("metric")) == 16
    # 步骤6：三域 14 表 body 带术语引用（id 取 term_create 返回），其余 15 表不带
    table_terms = {
        body["name"]: body.get("terms")
        for body in _client_mocks.asset_bodies
        if body["parent"].endswith(".hr")
    }
    assert len(table_terms) == 29
    assert sum(1 for terms in table_terms.values() if terms) == 14
    assert table_terms["job_requisitions"] == [
        {
            "id": "hr-domain.招聘管理",
            "type": "glossaryTerm",
            "fullyQualifiedName": "hr-domain.招聘管理",
            "displayName": "招聘管理",
        }
    ]
    assert table_terms["payroll_entries"][0]["fullyQualifiedName"] == "hr-domain.薪酬管理"
    assert table_terms["perf_reviews"][0]["fullyQualifiedName"] == "hr-domain.绩效管理"
    assert table_terms["employees"] is None
    # 六域挂载按新派生 FQN：Recruiting 6 / Compensation 5 / Performance 3 /
    # Workforce 8 / Attendance 5 / Approval 2
    mounted = dict(_client_mocks.bulks)
    assert len(_client_mocks.bulks) == 6
    assert set(mounted) == {f"HR.{d}" for d in _DOMAIN_NAMES}
    assert len(mounted["HR.Recruiting"]) == 6
    assert len(mounted["HR.Compensation"]) == 5
    assert len(mounted["HR.Performance"]) == 3
    assert len(mounted["HR.Workforce"]) == 8
    assert len(mounted["HR.Attendance"]) == 5
    assert len(mounted["HR.Approval"]) == 2
    # 步骤7：56 实体挂治理分类（29 表 + 7 域 + 术语表 + 3 术语 + 16 指标）
    assert len(_client_mocks.tag_applies) == 56
    by_collection: dict[str, list[str]] = {}
    for collection, entity_fqn, tag_fqn in _client_mocks.tag_applies:
        assert tag_fqn == "HR人力资源类"
        by_collection.setdefault(collection, []).append(entity_fqn)
    assert len(by_collection["tables"]) == 29
    assert set(by_collection["domains"]) == (
        {"HR"} | {f"HR.{d}" for d in _DOMAIN_NAMES}
    )
    assert by_collection["glossaries"] == ["hr-domain"]
    assert set(by_collection["glossaryTerms"]) == {
        f"hr-domain.{t}" for t in ("招聘管理", "薪酬管理", "绩效管理")
    }
    assert len(by_collection["metrics"]) == 16


async def test_provision_idempotent_when_all_exist(_client_mocks):
    """存量顶层域形态（无 parent）+ 存量表无 terms + 存量术语无 displayName：零新建
    + 6 域补挂主域 + 14 表补 terms + 3 术语补 displayName/synonyms"""
    _seed_existing(_client_mocks, service_connection={"config": {}})

    result = await provision_hr_assets(_mock_session())

    assert result == {
        "classifications": 0, "tables": 0, "domains": 0,
        "dataProducts": 0, "terms": 0, "metrics": 0,
    }
    # 单位按 name 幂等补建（get_unit 未命中即建），其余资产零新建
    assert [e for e in _client_mocks.created if e[0] != "unit"] == []
    # 存量六域补挂主域（FQN 列保持旧顶层值，仅 payload 写 /parent）+ 14 表补 terms
    parent_patches = [
        p
        for p in _client_mocks.patches
        if p[0] == "domain" and p[2][0]["path"] == "/parent"
    ]
    display_patches = [
        p
        for p in _client_mocks.patches
        if p[0] == "domain" and p[2][0]["path"] == "/displayName"
    ]
    table_patches = [p for p in _client_mocks.patches if p[0] == "table"]
    term_patches = [p for p in _client_mocks.patches if p[0] == "glossaryTerm"]
    # 存量六域补挂主域 + 补写中文 displayName（旧中英混合名 → 与 hr-open 域根一致）
    assert len(parent_patches) == 6
    for spec_key, _entity_id, operations in parent_patches:
        assert operations == [
            {
                "op": "add",
                "path": "/parent",
                "value": {"fullyQualifiedName": "HR", "type": "domain"},
            }
        ]
    assert len(display_patches) == 6
    for _spec_key, entity_id, operations in display_patches:
        assert operations == [
            {"op": "add", "path": "/displayName", "value": _DOMAIN_DISPLAY[entity_id]}
        ]
    # 三域 14 表存量补挂术语引用（先查 payload.terms 跳过，其余 15 表不 patch）
    assert len(table_patches) == 14
    for spec_key, _entity_id, operations in table_patches:
        assert spec_key == "table"
        assert operations[0]["path"] == "/terms"
        assert operations[0]["value"][0]["fullyQualifiedName"].startswith("hr-domain.")
    # 存量术语补 displayName/synonyms（单条 patch 双 op）
    assert len(term_patches) == 3
    for _spec_key, entity_id, operations in term_patches:
        assert operations == [
            {"op": "add", "path": "/displayName", "value": entity_id.rsplit(".", 1)[-1]},
            {"op": "add", "path": "/synonyms", "value": []},
        ]
    # 挂载仍执行，域引用按存量实际 FQN（顶层裸名）
    mounted = dict(_client_mocks.bulks)
    assert set(mounted) == set(_DOMAIN_NAMES)
    assert len(_client_mocks.bulks) == 6
    # tag 56 实体照发（已挂载 409 由真实 client 按幂等吞，替身不抛）
    assert len(_client_mocks.tag_applies) == 56


async def test_provision_idempotent_when_domains_already_nested(_client_mocks):
    """存量域已带 parent + displayName + 存量表已带 terms + 术语已带 displayName
    （补挂后的重跑形态）：零新建零 patch"""
    _seed_existing(
        _client_mocks,
        service_connection={"config": {}},
        domains_with_parent=True,
        tables_with_terms=True,
        terms_with_display=True,
        domains_with_display=True,
    )

    result = await provision_hr_assets(_mock_session())

    assert result == {
        "classifications": 0, "tables": 0, "domains": 0,
        "dataProducts": 0, "terms": 0, "metrics": 0,
    }
    assert [e for e in _client_mocks.created if e[0] != "unit"] == []
    assert _client_mocks.patches == []
    assert set(dict(_client_mocks.bulks)) == set(_DOMAIN_NAMES)


async def test_provision_backfills_connection_on_existing_service(_client_mocks):
    """存量服务 OM dict 无 connection 键时补写（存量租户幂等补偿路径）"""
    _seed_existing(
        _client_mocks,
        domains_with_parent=True,
        tables_with_terms=True,
        terms_with_display=True,
        domains_with_display=True,
    )

    with patch(
        "hr.services.ontology_provision_service._connection_config_from_settings",
        return_value=_FAKE_CONNECTION,
    ):
        result = await provision_hr_assets(_mock_session())

    assert result == {
        "classifications": 0, "tables": 0, "domains": 0,
        "dataProducts": 0, "terms": 0, "metrics": 0,
    }
    assert len(_client_mocks.patches) == 1
    spec_key, entity_id, operations = _client_mocks.patches[0]
    assert (spec_key, entity_id) == ("databaseService", "hr-pg")
    assert operations == [
        {"op": "add", "path": "/connection", "value": _FAKE_CONNECTION}
    ]


async def test_provision_omits_owner_when_iam_has_no_users(_client_mocks):
    """iam owner 角色无用户：owner 降级省略，管线照常完成"""

    class _EmptyIam:
        async def list_role_user_ids(self, session, tenant_id, role_code):
            return []

    with patch(
        "framework.clients.iam_client.get_iam_client",
        return_value=_EmptyIam(),
    ):
        result = await provision_hr_assets(_mock_session())

    assert result["dataProducts"] == 1
    assert all("owner" not in body for body in _client_mocks.domain_bodies)
    assert "owner" not in _client_mocks.product_bodies[0]


async def test_provision_omits_owner_when_iam_unavailable(_client_mocks):
    """iam 异常：owner 降级省略（warning 不阻塞），管线照常完成"""

    class _BrokenIam:
        async def list_role_user_ids(self, session, tenant_id, role_code):
            raise RuntimeError("iam 不可达")

    with patch(
        "framework.clients.iam_client.get_iam_client",
        return_value=_BrokenIam(),
    ):
        result = await provision_hr_assets(_mock_session())

    assert result["dataProducts"] == 1
    assert all("owner" not in body for body in _client_mocks.domain_bodies)
    assert "owner" not in _client_mocks.product_bodies[0]


async def test_provision_skips_when_ontology_absent():
    with (
        patch(
            "framework.clients.ontology_client.get_ontology_client",
            return_value=_DeadClient(),
        ),
        patch(
            "hr.services.ontology_provision_service._connection_config_from_settings",
            return_value=None,
        ),
    ):
        result = await provision_hr_assets(_mock_session())

    assert result is None
