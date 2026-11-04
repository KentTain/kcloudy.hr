"""渠道适配层 HTTP 底座（aiohttp 封装，传输可注入）。

- ``HttpTransport``：最小传输协议；生产用 ``AioHttpTransport``，单测注入 FakeTransport；
- ``ChannelHttpClient``：持 base_url 的 JSON 客户端，绝对 URL 透传（简历文件下载等）。
异常归一：网络层失败包装为 IntegrationNetworkError；HTTP 状态码/错误码判定
留给各 provider 客户端（三家「200 + body 错误码」约定不同）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import aiohttp

from hr.integration.errors import IntegrationNetworkError

DEFAULT_TIMEOUT_SECONDS = 15.0
CONNECT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class HttpResponse:
    """统一响应：status + 解析后的 JSON（非 JSON 时 data=None 保留 text）。"""

    status: int
    data: Any
    text: str
    url: str = ""


class HttpTransport(Protocol):
    """最小传输协议（生产 aiohttp / 测试 Fake）。"""

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        headers: dict | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> HttpResponse: ...


class AioHttpTransport:
    """aiohttp 传输实现：懒建会话，网络异常统一包装。"""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def aclose(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        headers: dict | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> HttpResponse:
        session = await self._ensure_session()
        client_timeout = aiohttp.ClientTimeout(
            total=timeout, connect=CONNECT_TIMEOUT_SECONDS
        )
        try:
            async with session.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=headers,
                timeout=client_timeout,
            ) as resp:
                text = await resp.text()
                data: Any = None
                try:
                    data = await resp.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError):
                    data = None
                return HttpResponse(
                    status=resp.status, data=data, text=text, url=str(resp.url)
                )
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            raise IntegrationNetworkError(f"渠道接口请求失败: {exc}") from exc


class ChannelHttpClient:
    """持 base_url 的 JSON 客户端（路径以 / 开头拼 base_url，绝对 URL 透传）。"""

    def __init__(
        self,
        base_url: str,
        *,
        transport: HttpTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = transport if transport is not None else AioHttpTransport()

    async def request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        headers: dict | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> HttpResponse:
        return await self._transport.request(
            method,
            self._absolute(path_or_url),
            params=params,
            json_body=json_body,
            headers=headers,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        if isinstance(self._transport, AioHttpTransport):
            await self._transport.aclose()

    def _absolute(self, path_or_url: str) -> str:
        if path_or_url.startswith(("http://", "https://")):
            return path_or_url
        host = urlsplit(self._base_url).hostname
        return f"{self._base_url}{path_or_url}" if host else path_or_url
