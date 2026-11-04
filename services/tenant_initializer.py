"""HR 租户初始化器

创建租户时按 framework TenantInitializer Protocol 执行：预置员工属性组
与薪酬项（渠道凭证/薪酬设置配置类型随 iam provision_structure 建好，
此处不重复）。注册于 application_web 启动注册表，注册序在 iam/hermes 之后。
"""

from loguru import logger

_logger = logger.bind(name=__name__)


class HrTenantInitializer:
    """HR 模块租户初始化（framework TenantInitializer Protocol 鸭子类型实现）"""

    async def initialize_tenant(
        self,
        session,
        tenant_id: str,
        creator_user_id: str | None = None,
    ) -> None:
        from hr.services.hr_seed_template import provision_field_groups, provision_salary_items

        groups = await provision_field_groups(session, tenant_id)
        items = await provision_salary_items(session, tenant_id)
        await self._provision_ontology(session, tenant_id)
        _logger.info(
            f"HR 租户初始化完成: tenant_id={tenant_id} field_groups={groups} salary_items={items}"
        )

    async def _provision_ontology(self, session, tenant_id: str) -> None:
        """ontology 资产注册（缺席/失败不阻塞租户创建，快照任务会幂等补偿）"""
        from framework.tenant.context import TenantContext
        from hr.services.ontology_provision_service import provision_hr_assets

        # ontology 仓储写入校验租户上下文（快照任务同款范式）；seed 等场景无请求上下文，此处显式设置
        previous_tenant_id = TenantContext.get_tenant_id()
        TenantContext.set_tenant_id(tenant_id)
        try:
            await provision_hr_assets(session)
        except Exception:  # noqa: BLE001
            _logger.exception(f"HR 资产 ontology 注册失败（留待快照补偿）: tenant={tenant_id}")
        finally:
            TenantContext.set_tenant_id(previous_tenant_id)


hr_tenant_initializer = HrTenantInitializer()
