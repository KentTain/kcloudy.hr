"""渠道客户端注册表：get_channel_client(code) → 渠道客户端单例。

Protocol 即扩展点：新渠道（Boss 直聘等）在 providers/ 下实现
RecruitingChannelClient 四能力并注册进 _CLIENTS 即接入。
"""

from __future__ import annotations

from hr.integration.errors import IntegrationConfigError
from hr.integration.http import HttpTransport
from hr.integration.providers.base import (
    ChannelApplication,
    ChannelResume,
    RecruitingChannelClient,
)
from hr.integration.providers.job51 import Job51ChannelClient
from hr.integration.providers.liepin import LiepinChannelClient
from hr.integration.providers.zhilian import ZhilianChannelClient

_CLIENT_FACTORIES: dict[str, type[RecruitingChannelClient]] = {
    "zhilian": ZhilianChannelClient,
    "job51": Job51ChannelClient,
    "liepin": LiepinChannelClient,
}

_instances: dict[str, RecruitingChannelClient] = {}


def get_channel_client(
    channel: str, *, transport: HttpTransport | None = None
) -> RecruitingChannelClient:
    """按渠道编码取客户端（transport 注入时新建实例，供测试桩替换）。"""
    if transport is not None:
        factory = _CLIENT_FACTORIES.get(channel)
        if factory is None:
            raise IntegrationConfigError(f"不支持的招聘渠道: {channel}")
        return factory(transport)
    if channel not in _instances:
        factory = _CLIENT_FACTORIES.get(channel)
        if factory is None:
            raise IntegrationConfigError(f"不支持的招聘渠道: {channel}")
        _instances[channel] = factory()
    return _instances[channel]


__all__ = [
    "ChannelApplication",
    "ChannelResume",
    "RecruitingChannelClient",
    "get_channel_client",
]
