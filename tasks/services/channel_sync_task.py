"""渠道定时同步任务：按 sync_interval_minutes 控频拉取各租户启用渠道

调度（每 10 分钟 tick）→ 跨租户扫描已发布外部渠道职位 → 逐 (租户, 渠道)
按同步间隔 Redis NX 抢频 → 渠道归集编排（幂等入库 + 通知）。
"""

from loguru import logger
from sqlalchemy import select

from framework.cache.redis_util import RedisUtil
from framework.database.dependencies import get_task_session
from framework.database.mixins.tenant import skip_tenant_filter
from framework.tenant.context import TenantContext

from hr.integration.credentials import (
    resolve_channel_credentials,
    resolve_sync_config,
)
from hr.models import JobPosting
from hr.services.channel_service import SYNC_ENABLED_CHANNELS, channel_service

_logger = logger.bind(name=__name__)

_SYNC_LOCK_KEY = "hr:channel:sync:lock:{tenant_id}:{channel}"


async def run_channel_sync_task() -> None:
    """渠道定时同步入口（apscheduler 每 10 分钟）。"""
    async with get_task_session() as session:
        with skip_tenant_filter():
            result = await session.execute(
                select(
                    JobPosting.tenant_id, JobPosting.channel
                ).distinct().where(
                    JobPosting.channel.in_(SYNC_ENABLED_CHANNELS),
                    JobPosting.status == "published",
                )
            )
            pairs = list(result.all())

        for tenant_id, channel in pairs:
            TenantContext.set_tenant_id(str(tenant_id))
            try:
                await _sync_if_due(session, str(tenant_id), channel)
                await session.commit()
            except Exception as exc:  # noqa: BLE001 — 单渠道失败不影响其余
                await session.rollback()
                _logger.exception(
                    f"渠道定时同步失败 tenant={tenant_id} channel={channel}: {exc}"
                )
            finally:
                TenantContext.clear()


async def _sync_if_due(session, tenant_id: str, channel: str) -> None:
    """按凭证块同步配置控频：间隔未到/未启用直接跳过。"""
    credentials = await resolve_channel_credentials(
        session, tenant_id, channel, check_enabled=False
    )
    sync_enabled, interval_minutes = resolve_sync_config(credentials)
    if not sync_enabled:
        return

    lock_key = _SYNC_LOCK_KEY.format(tenant_id=tenant_id, channel=channel)
    if not RedisUtil.is_initialized():
        return
    acquired = await RedisUtil.set(
        lock_key, "1", ttl=interval_minutes * 60, nx=True
    )
    if not acquired:
        return  # 间隔未到

    try:
        stat = await channel_service.sync_channel(session, tenant_id, channel)
    except Exception:
        await RedisUtil.delete(lock_key)  # 失败释放锁，下轮 tick 重试
        raise
    if not stat.get("skipped"):
        _logger.info(
            f"渠道定时同步完成 tenant={tenant_id} channel={channel} "
            f"fetched={stat.get('fetched')} new={stat.get('new')}"
        )
