"""hr → ontology 治理联动：数据资产/术语/指标注册管线

把 hr 全部业务表登记为 ontology 数据资产树（hr-pg 服务 / ai_platform 库 /
hr schema / 29 张业务表，六业务域全覆盖挂载），hr-domain 术语表与三域术语、
16 个指标注册口径。治理归类：HR人力资源类分类 56 实体根打标（tag_apply，
已挂载 409 按幂等吞）、HR人力资源域主域 + 六子域化、hr_core_assets 数据
产品挂主域；主域/子域/数据产品带 iam 租户管理员 owner 引用（解析失败降级
省略）；招聘/薪酬/绩效三域 14 表挂术语引用。连接配置从平台 sqlalchemy 配置
同源派生（连通测试与 postgres 质量执行开箱可用；存量服务缺连接配置时补写）。
全部按 FQN 先查后建幂等 upsert，重跑无重复；ontology 模块缺席（未启用）
优雅跳过，hr 主功能零依赖 ontology。

触发：HrTenantInitializer（新租户）+ 报表快照任务逐租户幂等补偿（既有租户）。
依赖方向 hr ──▶ framework 双模式客户端（framework/clients/ontology_client.py，
直调=进程内 provision 门面 / HTTP=inner 原语面），零 ontology 直接依赖；
租户身份取调用方压栈的 TenantContext（初始化器与快照任务均已显式设置）。
"""

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

_logger = logger.bind(name=__name__)

_ONTOLOGY_SERVICE = "hr-pg"
_ONTOLOGY_DB = "ai_platform"
_ONTOLOGY_SCHEMA = "hr"

# 治理目录归类（HR资产挂载ontology批B/C）：分类根打标 + 主域子域化 + 数据产品
# 根域/子域字段规范（2026-11-04 与 hr-open 包统一）：name 英文（FQN 标识符）、
# displayName 中文（展示），域根与子域 displayName 逐字对齐 hr-open 域根术语
_CLASSIFICATION_NAME = "HR人力资源类"
_CLASSIFICATION_DISPLAY = "HR 人力资源类"
_CLASSIFICATION_DESC = "HR 人力资源资产治理分类（表/域/术语族/指标统一挂载）"
_ROOT_DOMAIN_NAME = "HR"
_ROOT_DOMAIN_DISPLAY = "HR 人力资源域"
_ROOT_DOMAIN_DESC = "HR 六业务域主域（子域 parent 挂载父引用）"
_DATA_PRODUCT_NAME = "hr_core_assets"
_DATA_PRODUCT_DISPLAY = "HR 核心数据资产"
_DATA_PRODUCT_DESC = "HR 核心业务表数据资产产品（决策点 2 核验：一期仅建产品，表资产挂载后置）"

# 三域术语 → 表域映射（terms 挂载范围：招聘 6 / 薪酬 5 / 绩效 3 共 14 表）
_DOMAIN_TERMS = {
    "Recruiting": "招聘管理",
    "Compensation": "薪酬管理",
    "Performance": "绩效管理",
}

# 六业务域：name → (displayName, description)；displayName 与 hr-open 包域根术语逐字一致
_DOMAINS: tuple[tuple[str, str, str], ...] = (
    ("Recruiting", "招聘", "HR 招聘业务域（需求/渠道发布/候选人/漏斗/面试/Offer）"),
    ("Compensation", "薪酬", "HR 薪酬业务域（薪酬项/职级薪带/定薪调薪/发薪）"),
    ("Performance", "绩效", "HR 绩效业务域（考核周期/目标/评估校准）"),
    ("Workforce", "员工与组织", "HR 员工与组织业务域（主档/岗位/异动/合同/附件/扩展属性）"),
    ("Attendance", "考勤", "HR 考勤假勤业务域（考勤记录/导入/假期类型/余额/请假单）"),
    ("Approval", "审批", "HR 审批业务域（审批请求/审批流水）"),
)

# 29 张业务表全量登记：表名 → (域, 描述)
_TABLE_DOMAINS: tuple[tuple[str, str, str], ...] = (
    # Workforce 员工与组织域
    ("employees", "Workforce", "员工主档（工号/岗位职级/生命周期状态/入转调离日期）"),
    ("positions", "Workforce", "岗位（挂组织、带职级与编制）"),
    ("employee_changes", "Workforce", "异动流水（入职/转正/调动/级变/调薪/离职，前后快照留痕）"),
    ("employee_contracts", "Workforce", "员工合同"),
    ("employee_attachments", "Workforce", "员工材料附件"),
    ("employee_field_groups", "Workforce", "员工扩展属性组（EAV）"),
    ("employee_field_definitions", "Workforce", "员工扩展属性定义（EAV）"),
    ("employee_attribute_values", "Workforce", "员工扩展属性值（EAV，恒存字符串）"),
    # Recruiting 招聘域
    ("job_requisitions", "Recruiting", "招聘需求（需求编号/编制人数/薪酬区间/优先级）"),
    ("job_postings", "Recruiting", "渠道职位发布（内推/智联/前程无忧/猎聘）"),
    ("candidates", "Recruiting", "候选人（AI 简历归一、多渠道归集幂等）"),
    ("candidate_applications", "Recruiting", "投递申请（十阶段漏斗载体、AI 人岗匹配分）"),
    ("offers", "Recruiting", "Offer 单（定薪方案快照、发送/接受/拒绝）"),
    ("interviews", "Recruiting", "面试（轮次/形式/结果/AI 纪要）"),
    # Compensation 薪酬域
    ("salary_items", "Compensation", "薪酬项字典（基本/绩效/奖金/补贴/扣减，规则元数据）"),
    ("salary_bands", "Compensation", "职级薪带（区间下限/中位值/上限）"),
    ("employee_salary_packages", "Compensation", "员工定薪（区间版本化、hire/adjust/promotion/perf）"),
    ("payroll_runs", "Compensation", "发薪批次（期间租户唯一、draft→confirmed→paid 状态机）"),
    ("payroll_entries", "Compensation", "发薪明细（薪酬项金额，绩效系数联动试算）"),
    # Performance 绩效域
    ("perf_cycles", "Performance", "考核周期（draft→active→scoring→calibrating→closed 单向）"),
    ("perf_goals", "Performance", "绩效目标（权重合计 100、进度自动收口）"),
    ("perf_reviews", "Performance", "绩效评估（初评/校准评级 S/A/B/C/D、绩效系数）"),
    # Attendance 考勤假勤域
    ("attendance_records", "Attendance", "考勤记录（打卡/工时/加班、八态状态、excel/ai/leave 三来源）"),
    ("attendance_import_batches", "Attendance", "考勤导入批次（Excel/AI 双通道、行级校验明细）"),
    ("leave_types", "Attendance", "假期类型（天/小时计量、带薪、额度规则）"),
    ("leave_balances", "Attendance", "假期余额（员工×类型×年度，总额度-已用-冻结）"),
    ("leave_requests", "Attendance", "请假单（时长系统计算、审批通过与考勤联动）"),
    # Approval 审批域
    ("approval_requests", "Approval", "审批请求（hr 域内通用审批、池模式）"),
    ("approval_actions", "Approval", "审批流水（提交/通过/驳回/撤销逐次留痕）"),
)

_GLOSSARY_NAME = "hr-domain"
_GLOSSARY_DISPLAY = "HR 业务域术语表"

# 三域术语：name → (displayName, description)
_TERMS: tuple[tuple[str, str, str], ...] = (
    ("招聘管理", "招聘管理", "招聘需求、候选人、面试与 Offer 全流程管理"),
    ("薪酬管理", "薪酬管理", "薪酬项、职级薪带、定薪与发薪核算"),
    ("绩效管理", "绩效管理", "考核周期、目标、评分与校准"),
)

# 计量单位：name → displayName（指标 unitOfMeasurement 引用前置）
_UNITS: tuple[tuple[str, str], ...] = (
    ("percent", "百分比"),
    ("count", "计数"),
    ("day", "天"),
    ("hour", "小时"),
    ("cny", "元"),
    ("ratio", "比率"),
)

# 指标注册口径（attrition_rate/headcount_gap/perf_rating_distribution 与
# report_service._BUILTIN_METRICS 白名单同源，FQN 不可改）
_METRICS: dict[str, dict] = {
    "attrition_rate": {
        "displayName": "离职率",
        "description": "当月离职人数 / 当月平均在编人数（百分数），按员工生命周期月末口径回算",
        "unitOfMeasurement": "percent",
    },
    "headcount_gap": {
        "displayName": "编制缺口",
        "description": "在编人数统计（active = probation/regular），与组织编制基准的缺口汇总",
        "unitOfMeasurement": "count",
    },
    "perf_rating_distribution": {
        "displayName": "绩效评级分布",
        "description": "已收口周期内员工评级分布（校准评级优先），总人数按评估记录行数累计",
        "unitOfMeasurement": "percent",
    },
    # ── Workforce 员工与组织 ──
    "workforce_headcount": {
        "displayName": "在编人数",
        "description": "employees.status ∈ (probation, regular) 的员工数（试用期与正式在编）",
        "unitOfMeasurement": "count",
    },
    "workforce_transfer_rate": {
        "displayName": "月度异动率",
        "description": "当月生效异动流水数 / 在编人数（employee_changes.effective_date 当月口径）",
        "unitOfMeasurement": "percent",
    },
    # ── Recruiting 招聘 ──
    "recruiting_time_to_hire": {
        "displayName": "平均到岗周期",
        "description": "candidate_applications.apply_time 起算至 stage 流转入 onboarded 的平均自然日",
        "unitOfMeasurement": "day",
    },
    "recruiting_offer_acceptance_rate": {
        "displayName": "offer 接受率",
        "description": "offers.status = accepted / (accepted + rejected)，口径挂 Offer 单状态机",
        "unitOfMeasurement": "percent",
    },
    "recruiting_funnel_conversion_rate": {
        "displayName": "漏斗转化率",
        "description": "进入 interviewing 及之后阶段的申请数 / 全部申请数（candidate_applications.stage 十态）",
        "unitOfMeasurement": "percent",
    },
    # ── Compensation 薪酬 ──
    "comp_payroll_total": {
        "displayName": "月度发薪总额",
        "description": "payroll_entries.amount 按已支付（paid）批次期间求和，金额单位元",
        "unitOfMeasurement": "cny",
    },
    "comp_payroll_per_capita": {
        "displayName": "人均发薪",
        "description": "月度发薪总额 / 批次发放人数（payroll_runs.employee_count 回写口径）",
        "unitOfMeasurement": "cny",
    },
    "comp_band_compa_ratio": {
        "displayName": "薪带比较比率",
        "description": "员工定薪 / 所在职级薪带中位值（employee_salary_packages 对标 salary_bands 区间中位）",
        "unitOfMeasurement": "ratio",
    },
    # ── Performance 绩效 ──
    "perf_goal_completion_rate": {
        "displayName": "目标达成率",
        "description": "周期内 perf_goals.status = completed 的目标数 / 全部目标数",
        "unitOfMeasurement": "percent",
    },
    "perf_high_rating_ratio": {
        "displayName": "高绩效占比",
        "description": "校准评级优先（calibrated_rating 回退 rating）∈ (S, A) 的评估 / 全部评估",
        "unitOfMeasurement": "percent",
    },
    # ── Attendance 考勤假勤 ──
    "attendance_absence_rate": {
        "displayName": "缺勤率",
        "description": "attendance_records.status ∈ (absent, missing_card) 记录 / 全部考勤记录",
        "unitOfMeasurement": "percent",
    },
    "attendance_overtime_total": {
        "displayName": "月度加班总时长",
        "description": "attendance_records.overtime_hours 按自然月求和，单位小时",
        "unitOfMeasurement": "hour",
    },
    "leave_usage_rate": {
        "displayName": "假期使用率",
        "description": "leave_balances 已用 / 总额度（used / total_quota，年度口径）",
        "unitOfMeasurement": "percent",
    },
}


def _connection_config_from_settings() -> dict | None:
    """从平台 sqlalchemy URL 同源派生 hr-pg 连接配置；URL 缺失/解析失败返回 None。"""
    from urllib.parse import unquote, urlparse

    from framework.configs.settings import get_settings

    url = get_settings().sqlalchemy.url
    if not url:
        return None
    parsed = urlparse(url)
    database = (parsed.path or "").lstrip("/")
    if not parsed.hostname or not parsed.port or not database:
        return None
    return {
        "config": {
            "type": "Postgres",
            "hostPort": f"{parsed.hostname}:{parsed.port}",
            "username": unquote(parsed.username or ""),
            "password": unquote(parsed.password or ""),
            "database": database,
        }
    }


async def _resolve_owner(client, session: AsyncSession, tenant_id: str) -> dict | None:
    """iam 租户管理员（owner 角色）引用；无用户/解析失败降级省略（warning 不阻塞）。

    iam_client 无现成「租户管理员」查询接口，经 owner 角色用户解析
    （role_code=`{tenant_id}:owner`，取首用户），下轮快照补偿可重试。
    """
    try:
        from framework.clients.iam_client import get_iam_client

        iam = get_iam_client()
        user_ids = await iam.list_role_user_ids(session, tenant_id, f"{tenant_id}:owner")
        if not user_ids:
            _logger.warning("iam 租户 owner 角色无用户，实体省略 owner 引用")
            return None
        users = await iam.get_users_batch(session, [user_ids[0]])
        if not users:
            _logger.warning("iam owner 用户档案缺失，实体省略 owner 引用")
            return None
        user = users[0]
        return {
            "id": user.id,
            "type": "user",
            "displayName": user.nickname or user.username,
        }
    except Exception as exc:
        _logger.warning(f"iam 管理员解析失败，实体省略 owner 引用: {exc}")
        return None


def _terms_reference(term_ids: dict[str, str], term_name: str) -> list[dict] | None:
    """术语引用形态（id 经 term_create 返回/存量回查收集）；术语缺席返回 None。"""
    term_id = term_ids.get(term_name)
    if term_id is None:
        return None
    return [
        {
            "id": term_id,
            "type": "glossaryTerm",
            "fullyQualifiedName": f"{_GLOSSARY_NAME}.{term_name}",
            "displayName": term_name,
        }
    ]


async def provision_hr_assets(session: AsyncSession) -> dict[str, int] | None:
    """幂等注册 hr 资产/域/术语/指标；ontology 缺席返回 None。

    savepoint 隔离：注册中途失败整体回滚到注册前，不污染调用方事务
    （租户创建/快照任务由调用方捕获异常记日志继续）。
    """
    from framework.clients.ontology_client import (
        OntologyConflictError,
        OntologyUnavailableError,
        get_ontology_client,
    )
    from framework.tenant.context import TenantContext

    tenant_id = TenantContext.get_tenant_id()
    client = get_ontology_client()

    created = {
        "classifications": 0,
        "tables": 0,
        "domains": 0,
        "dataProducts": 0,
        "terms": 0,
        "metrics": 0,
    }
    try:
        async with session.begin_nested():
            # 步骤1：治理分类（分类根打标载体，tagFQN=分类名）
            if await client.entity_get_by_fqn(
                session, tenant_id=tenant_id,
                spec_key="classification", fqn=_CLASSIFICATION_NAME,
            ) is None:
                await client.entity_create(
                    session,
                    tenant_id=tenant_id,
                    spec_key="classification",
                    name=_CLASSIFICATION_NAME,
                    payload={
                        "displayName": _CLASSIFICATION_DISPLAY,
                        "description": _CLASSIFICATION_DESC,
                        "mutuallyExclusive": False,
                    },
                )
                created["classifications"] += 1

            # 步骤5 前置：iam 租户管理员 owner 引用（主域/子域/数据产品创建 body 携带）
            owner = await _resolve_owner(client, session, tenant_id)

            # 步骤2：主域（六业务域 parent 挂载目标）
            if await client.entity_get_by_fqn(
                session, tenant_id=tenant_id, spec_key="domain", fqn=_ROOT_DOMAIN_NAME,
            ) is None:
                root_body: dict = {
                    "name": _ROOT_DOMAIN_NAME,
                    "displayName": _ROOT_DOMAIN_DISPLAY,
                    "description": _ROOT_DOMAIN_DESC,
                    "domainType": "Aggregate",
                }
                if owner:
                    root_body["owner"] = owner
                await client.domain_create(session, tenant_id=tenant_id, body=root_body)
                created["domains"] += 1

            svc_fqn = _ONTOLOGY_SERVICE
            connection = _connection_config_from_settings()
            service = await client.entity_get_by_fqn(
                session, tenant_id=tenant_id, spec_key="databaseService", fqn=svc_fqn
            )
            if service is None:
                body: dict = {
                    "name": svc_fqn,
                    "serviceType": "Postgres",
                    "description": "HR 平台主库服务",
                }
                if connection is not None:
                    body["connection"] = connection
                await client.service_create(
                    session, tenant_id=tenant_id, service_type="databaseService", body=body
                )
            elif connection is not None and "connection" not in service:
                # 存量服务缺连接配置：补写（连通测试/质量执行开箱可用）
                await client.entity_patch(
                    session,
                    tenant_id=tenant_id,
                    spec_key="databaseService",
                    entity_id=service["id"],
                    ops=[{"op": "add", "path": "/connection", "value": connection}],
                )
                _logger.info("hr-pg 服务补写连接配置（存量幂等补偿）")

            db_fqn = f"{svc_fqn}.{_ONTOLOGY_DB}"
            if await client.entity_get_by_fqn(
                session, tenant_id=tenant_id, spec_key="database", fqn=db_fqn
            ) is None:
                await client.asset_create(
                    session,
                    tenant_id=tenant_id,
                    asset_type="database",
                    body={
                        "name": _ONTOLOGY_DB,
                        "parent": svc_fqn,
                        "description": "HR 平台主库",
                    },
                )

            schema_fqn = f"{db_fqn}.{_ONTOLOGY_SCHEMA}"
            if await client.entity_get_by_fqn(
                session, tenant_id=tenant_id, spec_key="databaseSchema", fqn=schema_fqn
            ) is None:
                await client.asset_create(
                    session,
                    tenant_id=tenant_id,
                    asset_type="databaseSchema",
                    body={"name": _ONTOLOGY_SCHEMA, "parent": db_fqn},
                )

            # 步骤6 前置：术语表 + 三域术语先建（表创建 body 需术语 id 构造引用）
            if await client.entity_get_by_fqn(
                session, tenant_id=tenant_id, spec_key="glossary", fqn=_GLOSSARY_NAME
            ) is None:
                await client.entity_create(
                    session,
                    tenant_id=tenant_id,
                    spec_key="glossary",
                    name=_GLOSSARY_NAME,
                    payload={"displayName": _GLOSSARY_DISPLAY},
                )
            term_ids: dict[str, str] = {}
            for term_name, display, description in _TERMS:
                term_fqn = f"{_GLOSSARY_NAME}.{term_name}"
                existing_term = await client.entity_get_by_fqn(
                    session, tenant_id=tenant_id, spec_key="glossaryTerm", fqn=term_fqn
                )
                if existing_term is None:
                    created_term = await client.term_create(
                        session,
                        tenant_id=tenant_id,
                        body={
                            "name": term_name,
                            "glossary": _GLOSSARY_NAME,
                            "displayName": display,
                            "synonyms": [],
                            "description": description,
                        },
                    )
                    term_ids[term_name] = created_term["id"]
                    created["terms"] += 1
                else:
                    # 存量术语缺 displayName/synonyms 键补写（响应为摊平形态，
                    # 键缺失才 patch，避免补偿任务空转递增版本）
                    ops = []
                    if "displayName" not in existing_term:
                        ops.append({"op": "add", "path": "/displayName", "value": display})
                    if "synonyms" not in existing_term:
                        ops.append({"op": "add", "path": "/synonyms", "value": []})
                    if ops:
                        await client.entity_patch(
                            session,
                            tenant_id=tenant_id,
                            spec_key="glossaryTerm",
                            entity_id=existing_term["id"],
                            ops=ops,
                        )
                        _logger.info(f"存量术语 {term_fqn} 补写 displayName/synonyms（幂等补偿）")
                    term_ids[term_name] = existing_term["id"]

            table_fqns = {
                f"{schema_fqn}.{table}": (table, domain)
                for table, domain, _ in _TABLE_DOMAINS
            }
            # include_deleted=True：软删实体仍占 FQN（create 唯一性检查含软删），
            # 预检漏看会导致每次补偿重试必报 EntityConflictError 并整体回滚
            existing_tables = {
                entity["fullyQualifiedName"]: entity
                for entity in await client.entity_get_by_fqns(
                    session, tenant_id=tenant_id, spec_key="table",
                    fqns=list(table_fqns), include_deleted=True,
                )
            }
            descriptions = {table: desc for table, _, desc in _TABLE_DOMAINS}
            for fqn, (table, domain) in table_fqns.items():
                term_name = _DOMAIN_TERMS.get(domain)
                terms_ref = _terms_reference(term_ids, term_name) if term_name else None
                if fqn in existing_tables:
                    if existing_tables[fqn].get("deleted"):
                        # 软删保留的 FQN：尊重删除意图，跳过重建与 terms 补写
                        _logger.info(f"存量表 {fqn} 已软删，跳过注册（幂等补偿不复活）")
                        continue
                    # 存量表 terms 先查跳过（terms 非 HEAVY_FIELDS，读面可见）
                    if terms_ref and "terms" not in existing_tables[fqn]:
                        await client.entity_patch(
                            session,
                            tenant_id=tenant_id,
                            spec_key="table",
                            entity_id=existing_tables[fqn]["id"],
                            ops=[{"op": "add", "path": "/terms", "value": terms_ref}],
                        )
                    continue
                body: dict = {
                    "name": table,
                    "parent": schema_fqn,
                    "description": descriptions[table],
                }
                if terms_ref:
                    body["terms"] = terms_ref
                await client.asset_create(
                    session, tenant_id=tenant_id, asset_type="table", body=body
                )
                created["tables"] += 1
            # 域-资产挂载排除软删表：预检对软删行「跳过不复活」，行不存在于读面
            # （_resolve_asset_refs 按非软删解析），带上会 EntityNotFoundError
            # 整体回滚注册事务
            soft_deleted_tables = {
                fqn
                for fqn, entity in existing_tables.items()
                if entity.get("deleted")
            }
            domain_tables: dict[str, list[dict]] = {}
            for table, domain, _ in _TABLE_DOMAINS:
                table_fqn = f"{schema_fqn}.{table}"
                if table_fqn in soft_deleted_tables:
                    continue
                domain_tables.setdefault(domain, []).append(
                    {"type": "table", "fullyQualifiedName": table_fqn}
                )

            # 步骤3：子域化 + 步骤8：域-资产挂载（domain_name 按实体实际 FQN）
            domain_fqns_actual: list[str] = []
            for name, display, description in _DOMAINS:
                existing = await client.entity_get_by_fqn(
                    session, tenant_id=tenant_id, spec_key="domain", fqn=name
                )
                if existing is None:
                    # 新建子域：FQN 严格派生为 {主域}.{域名}
                    domain_fqn = f"{_ROOT_DOMAIN_NAME}.{name}"
                    if await client.entity_get_by_fqn(
                        session, tenant_id=tenant_id, spec_key="domain", fqn=domain_fqn,
                    ) is None:
                        body: dict = {
                            "name": name,
                            "displayName": display,
                            "description": description,
                            "domainType": "Aggregate",
                            "parent": _ROOT_DOMAIN_NAME,
                        }
                        if owner:
                            body["owner"] = owner
                        await client.domain_create(session, tenant_id=tenant_id, body=body)
                        created["domains"] += 1
                else:
                    # 存量顶层域补挂主域：patch 只写 payload，FQN 列保持旧顶层值（双形态并存）
                    if "parent" not in existing:
                        await client.entity_patch(
                            session,
                            tenant_id=tenant_id,
                            spec_key="domain",
                            entity_id=existing["id"],
                            ops=[
                                {
                                    "op": "add",
                                    "path": "/parent",
                                    "value": {
                                        "fullyQualifiedName": _ROOT_DOMAIN_NAME,
                                        "type": "domain",
                                    },
                                }
                            ],
                        )
                    # 存量 displayName 对齐补丁（旧中英混合名 → 与 hr-open 域根术语一致）
                    if existing.get("displayName") != display:
                        await client.entity_patch(
                            session,
                            tenant_id=tenant_id,
                            spec_key="domain",
                            entity_id=existing["id"],
                            ops=[{"op": "add", "path": "/displayName", "value": display}],
                        )
                        _logger.info(f"存量子域 {name} displayName 补写为「{display}」（幂等补偿）")
                    domain_fqn = name
                domain_fqns_actual.append(domain_fqn)
                # bulk_add_assets 内部按边存在性幂等跳过
                if domain_tables.get(name):
                    await client.domain_bulk_add_assets(
                        session, tenant_id=tenant_id, domain_name=domain_fqn, assets=domain_tables[name]
                    )

            # 步骤4：数据产品挂主域（决策点 2 核验：一期仅建产品不挂表资产，见常量注）
            product_fqn = f"{_ROOT_DOMAIN_NAME}.{_DATA_PRODUCT_NAME}"
            if await client.entity_get_by_fqn(
                session, tenant_id=tenant_id, spec_key="dataProduct", fqn=product_fqn,
            ) is None:
                product_body: dict = {
                    "name": _DATA_PRODUCT_NAME,
                    "domain": _ROOT_DOMAIN_NAME,
                    "displayName": _DATA_PRODUCT_DISPLAY,
                    "description": _DATA_PRODUCT_DESC,
                }
                if owner:
                    product_body["owner"] = owner
                await client.data_product_create(session, tenant_id=tenant_id, body=product_body)
                created["dataProducts"] += 1

            for unit_name, display in _UNITS:
                # create_metric 校验 unitOfMeasurement 引用已登记单位，先保单位存在
                if await client.unit_get(session, tenant_id=tenant_id, name=unit_name) is None:
                    await client.unit_create(
                        session, tenant_id=tenant_id, body={"name": unit_name, "displayName": display}
                    )
            for name, payload in _METRICS.items():
                if await client.entity_get_by_fqn(
                    session, tenant_id=tenant_id, spec_key="metric", fqn=name
                ) is None:
                    await client.metric_create(
                        session, tenant_id=tenant_id, body={"name": name, **payload}
                    )
                    created["metrics"] += 1

            # 步骤7：56 实体挂治理分类（29 表 + 主域 + 6 子域 + 术语表 + 3 术语 + 16 指标；
            # tags 属 HEAVY_FIELDS 读面不可见，已挂载 409 按幂等吞不视为失败；
            # 软删表不在读面，与域挂载同口径排除，否则 tag_apply 报实体不存在整体回滚）
            tag_targets: list[tuple[str, str]] = [
                ("domains", _ROOT_DOMAIN_NAME),
                *[("domains", fqn) for fqn in domain_fqns_actual],
                *[("tables", fqn) for fqn in table_fqns if fqn not in soft_deleted_tables],
                ("glossaries", _GLOSSARY_NAME),
                *[("glossaryTerms", f"{_GLOSSARY_NAME}.{name}") for name, _, _ in _TERMS],
                *[("metrics", name) for name in _METRICS],
            ]
            for collection, entity_fqn in tag_targets:
                try:
                    await client.tag_apply(
                        session,
                        tenant_id=tenant_id,
                        collection=collection,
                        entity_fqn=entity_fqn,
                        tag_fqn=_CLASSIFICATION_NAME,
                    )
                except OntologyConflictError:
                    pass
    except OntologyUnavailableError:
        _logger.info("ontology 模块缺席，跳过 hr 资产注册")
        return None

    _logger.info(f"hr 资产注册完成（新建 {created}，既有项幂等跳过）")
    return created
