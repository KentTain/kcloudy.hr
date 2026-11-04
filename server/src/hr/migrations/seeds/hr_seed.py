"""HR 默认租户种子数据初始化

为默认租户按模板幂等预置员工属性组与薪酬项（新租户经 HrTenantInitializer
同源补建，双通道同源 hr/services/hr_seed_template.py）。
"""

from __future__ import annotations

from framework.utils.log_util import write_success
from hr.services.hr_seed_template import provision_field_groups, provision_salary_items


async def run(*, dry_run: bool = False) -> int:
    """初始化默认租户 HR 种子数据

    Args:
        dry_run: 仅预览，不写入数据库

    Returns:
        初始化的记录数
    """
    from framework.configs import get_settings
    from framework.database.core.engine import get_session

    settings = get_settings()
    tenant_id = settings.tenant.default_tenant_id

    async with get_session() as session:
        if dry_run:
            return 0
        groups = await provision_field_groups(session, tenant_id)
        items = await provision_salary_items(session, tenant_id)
        await session.commit()

    total = groups + items
    if total:
        write_success(f"[hr] 默认租户种子数据初始化完成: 属性组 {groups} + 薪酬项 {items}")
    return total
