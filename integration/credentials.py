"""招聘渠道凭证解析与 Redis token 缓存。

凭证承载为 SystemSetting 单块 ``hr_channel_{code}``（属性：app_key /
app_secret（sensitive 密文）/ enabled / sync_enabled / sync_interval_minutes），
经 iam_client 只读解析（跨模块禁直接读 iam 模型；app_secret 落库密文，
get_values 返回密文，本模块负责解密）。

token 走 RedisUtil 缓存，key ``hr:channel:token:{tenant_id}:{channel}``；
Redis 不可用直接透传不缓存（可用性优先，iam integration 同款纪律）。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from framework.cache.redis_util import RedisUtil
from framework.clients.iam_client import get_iam_client
from framework.utils.crypto import CryptoError
from framework.utils.resource_crypto import decrypt_password

from hr.integration.errors import (
    IntegrationConfigError,
    IntegrationDisabledError,
)

# 一期外部招聘渠道（internal 为内置免凭证渠道，不走适配层）
CHANNELS = ("zhilian", "job51", "liepin")

CHANNEL_SETTING_CODE_PREFIX = "hr_channel_"

TOKEN_CACHE_PREFIX = "hr:channel:token:"

# token 提前刷新余量与下限（秒），iam integration 同款纪律
_TOKEN_REFRESH_MARGIN = 120
_TOKEN_TTL_FLOOR = 60


def channel_setting_code(channel: str) -> str:
    return f"{CHANNEL_SETTING_CODE_PREFIX}{channel}"


def resolve_sync_config(credentials: dict) -> tuple[bool, int]:
    """从凭证字典提取同步配置（sync_enabled 默认开，间隔默认 60 分钟）。

    间隔非法/非正值回退默认 60；下限 5 分钟防误配高频拉取。
    """
    enabled = credentials.get("sync_enabled", True)
    if isinstance(enabled, str):
        enabled = enabled.lower() == "true"
    raw = credentials.get("sync_interval_minutes")
    try:
        interval = int(raw)
    except (TypeError, ValueError):
        interval = 60
    if interval <= 0:
        interval = 60
    return bool(enabled), max(interval, 5)


async def resolve_channel_credentials(
    session: AsyncSession,
    tenant_id: str,
    channel: str,
    *,
    check_enabled: bool = True,
) -> dict:
    """解析渠道凭证块（hr_channel_{channel} → 属性字典，app_secret 已解密）。

    块缺失 → IntegrationConfigError；check_enabled 且 enabled 非 true →
    IntegrationDisabledError；app_secret 解密失败 → IntegrationConfigError。
    """
    values = await get_iam_client().get_system_setting(
        session, tenant_id, channel_setting_code(channel)
    )
    if values is None:
        raise IntegrationConfigError(f"渠道 {channel} 凭证块未配置")
    if check_enabled and not _is_enabled(values):
        raise IntegrationDisabledError(f"渠道 {channel} 未启用")

    credentials = {k: v for k, v in values.items() if v is not None}
    secret = credentials.get("app_secret")
    if secret:
        try:
            credentials["app_secret"] = decrypt_password(str(secret))
        except CryptoError as exc:
            raise IntegrationConfigError(
                f"渠道 {channel} 凭证 app_secret 解密失败，请重新编辑保存凭证"
            ) from exc
    return credentials


def _is_enabled(values: dict) -> bool:
    enabled = values.get("enabled")
    if isinstance(enabled, str):
        return enabled.lower() == "true"
    return bool(enabled)


# --------------------------------------------------------------------- token 缓存


def _token_cache_key(tenant_id: str, channel: str) -> str:
    return f"{TOKEN_CACHE_PREFIX}{tenant_id}:{channel}"


def token_ttl_seconds(expires_in: int | float | None) -> int:
    """缓存 TTL：提前 120s 刷新，下限 60s（防渠道返回极短有效期直接穿透）。"""
    expires = int(expires_in or 7200)
    return max(expires - _TOKEN_REFRESH_MARGIN, _TOKEN_TTL_FLOOR)


async def get_cached_token(tenant_id: str, channel: str) -> str | None:
    if not RedisUtil.is_initialized():
        return None
    return await RedisUtil.get(_token_cache_key(tenant_id, channel))


async def cache_token(
    tenant_id: str, channel: str, token: str, expires_in: int | None
) -> None:
    if not RedisUtil.is_initialized():
        return
    await RedisUtil.set(
        _token_cache_key(tenant_id, channel),
        token,
        ttl=token_ttl_seconds(expires_in),
    )


async def invalidate_token(tenant_id: str, channel: str) -> None:
    if not RedisUtil.is_initialized():
        return
    await RedisUtil.delete(_token_cache_key(tenant_id, channel))
