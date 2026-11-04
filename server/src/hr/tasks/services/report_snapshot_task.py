"""报表快照任务

每日跨租户刷新四域报表快照（personnel 人事趋势 / recruiting 招聘月度桶 /
compensation 薪酬分布 / performance 绩效分布，固定近 12 月口径），
写 Redis 缓存供报表接口快速返回；幂等覆盖写，失败不影响次日重算。
任务会话无租户上下文，逐租户显式设定上下文后复用服务口径（compute_* 直算）。
"""

import json

from loguru import logger
from sqlalchemy import select

from framework.cache.redis_util import RedisUtil
from framework.configs.settings import get_settings
from framework.database.dependencies import get_task_session
from framework.lock.factory import get_lock_provider
from framework.tenant.context import TenantContext

from hr.models import Employee

_logger = logger.bind(name=__name__)

REPORT_SNAPSHOT_LOCK_KEY = "lock:hr:report-snapshot"
REPORT_SNAPSHOT_LOCK_TTL_SECONDS = 300
SNAPSHOT_MONTHS = 12


async def run_report_snapshot_task() -> None:
    """报表快照任务（每日一次，逐租户覆盖写四域快照缓存）"""
    from hr.services.report_service import (
        SNAPSHOT_KEY_PREFIX,
        SNAPSHOT_TTL_SECONDS,
        report_service,
    )

    try:
        lock_provider = get_lock_provider(get_settings().lock)
    except Exception:
        _logger.exception("报表快照任务获取锁提供者失败")
        return

    async with lock_provider.acquire_context(
        REPORT_SNAPSHOT_LOCK_KEY, ttl=REPORT_SNAPSHOT_LOCK_TTL_SECONDS, timeout=0
    ) as lock:
        if lock is None:
            _logger.info("报表快照任务已被其他实例锁定，跳过本轮")
            return

        async with get_task_session() as session:
            tenant_rows = (
                await session.execute(
                    select(Employee.tenant_id)
                    .distinct()
                    .order_by(Employee.tenant_id)
                )
            ).scalars().all()
            refreshed = 0
            failed = 0
            for tenant_id in tenant_rows:
                TenantContext.set_tenant_id(tenant_id)
                try:
                    payloads = await _compute_domain_payloads(session)
                    for domain, payload in payloads.items():
                        await RedisUtil.set(
                            f"{SNAPSHOT_KEY_PREFIX}{domain}",
                            # default=str：载荷可能含 date/datetime（部分租户数据触发）
                            json.dumps(payload, ensure_ascii=False, default=str),
                            ttl=SNAPSHOT_TTL_SECONDS,
                        )
                    refreshed += 1
                    await _compensate_ontology_provision(session, tenant_id)
                except Exception as error:  # noqa: BLE001 单租户失败不阻塞整轮
                    failed += 1
                    _logger.error(
                        f"报表快照刷新失败: tenant={tenant_id} error={error}"
                    )
                finally:
                    TenantContext.clear()

        _logger.info(
            f"报表快照任务完成: 租户={len(tenant_rows)} 刷新={refreshed} 失败={failed}"
        )


async def _compensate_ontology_provision(session, tenant_id: str) -> None:
    """快照后幂等补偿 ontology 资产注册（既有租户补注册；失败仅告警）"""
    from hr.services.ontology_provision_service import provision_hr_assets

    try:
        await provision_hr_assets(session)
    except Exception:  # noqa: BLE001 补偿失败不影响快照结果
        _logger.exception(f"ontology 资产注册补偿失败: tenant={tenant_id}")


async def _compute_domain_payloads(session) -> dict[str, dict]:
    """四域快照载荷（personnel 复用快照口径，其余走 compute_* 直算）。"""
    from datetime import date

    from hr.services.report_service import (
        SNAPSHOT_MONTHS,
        build_month_range,
        compute_headcount_trend,
        compute_turnover,
        report_service,
    )

    lifecycles = (
        (
            await session.execute(
                select(Employee.hire_date, Employee.offboard_date).where(
                    Employee.hire_date.is_not(None)
                )
            )
        )
        .all()
    )
    pairs = [
        (hire_date, offboard_date) for hire_date, offboard_date in lifecycles
    ]
    months_range = build_month_range(SNAPSHOT_MONTHS)
    return {
        "personnel": {
            "headcount_trend": [
                item.model_dump()
                for item in compute_headcount_trend(pairs, months_range)
            ],
            "turnover": [
                item.model_dump() for item in compute_turnover(pairs, months_range)
            ],
            "computed_at": date.today().isoformat(),
        },
        "recruiting": await report_service.compute_recruiting_snapshot(session),
        "compensation": (await report_service.compute_comp_distribution(session)).model_dump(),
        "performance": (await report_service.compute_performance(session)).model_dump(),
    }
