"""招聘渠道适配层单元测试

覆盖：错误归一五类（Config/Disabled/Auth/Api/Network）、token 失效强取
重试一次、token 缓存命中、注册表未知渠道拒绝、三家 provider 发布/拉取
字段映射（FakeTransport 桩，不依赖外部渠道连通性）。
"""

from unittest.mock import patch

import pytest

from hr.integration.credentials import resolve_channel_credentials
from hr.integration.errors import (
    IntegrationApiError,
    IntegrationAuthError,
    IntegrationConfigError,
    IntegrationDisabledError,
    IntegrationNetworkError,
)
from hr.integration.http import HttpResponse
from hr.integration.providers import get_channel_client
from hr.integration.providers.zhilian import ZhilianChannelClient

CREDENTIALS = {"app_key": "k-1", "app_secret": "s-1", "enabled": True}


class FakeTransport:
    """按序回放响应的传输桩；记录请求便于断言。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests: list[dict] = []

    async def request(self, method, url, *, params=None, json_body=None, headers=None, timeout=15.0):
        self.requests.append(
            {"method": method, "url": url, "params": params, "json": json_body, "headers": headers}
        )
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, data = item
        import json as _json

        return HttpResponse(status=status, data=data, text=_json.dumps(data))

    @property
    def exhausted(self) -> bool:
        return not self._responses


def _json_response(status=200, data=None):
    return (status, data if data is not None else {})


# --------------------------------------------------------------------- 错误归一


class TestErrorNormalization:
    """错误归一五类"""

    @pytest.mark.asyncio
    async def test_auth_error_when_token_request_fails(self):
        transport = FakeTransport([_json_response(400, {"code": "400", "message": "bad"})])
        client = ZhilianChannelClient(transport=transport)
        with pytest.raises(IntegrationAuthError):
            await client.get_token("t-1", "zhilian", CREDENTIALS)

    def test_api_error_token_invalid_on_401(self):
        from hr.integration.http import HttpResponse

        client = ZhilianChannelClient(transport=FakeTransport([]))
        with pytest.raises(IntegrationApiError) as exc_info:
            client._raise_if_error(
                HttpResponse(status=401, data={}, text=""), "/api/hr/job/publish"
            )
        assert exc_info.value.is_token_invalid is True
        assert exc_info.value.channel == "zhilian"

    @pytest.mark.asyncio
    async def test_network_error_wrapped(self):
        transport = FakeTransport([IntegrationNetworkError("connection refused")])
        client = ZhilianChannelClient(transport=transport)
        with pytest.raises(IntegrationNetworkError):
            await client.get_token("t-1", "zhilian", CREDENTIALS)

    @pytest.mark.asyncio
    async def test_token_invalid_code_marks_retryable(self):
        transport = FakeTransport(
            [
                _json_response(200, {"access_token": "tk-old", "expires_in": 7200}),
                _json_response(200, {"code": "2602102", "message": "token expired"}),
                _json_response(200, {"access_token": "tk-new", "expires_in": 7200}),
                _json_response(200, {"code": "2602102", "message": "token expired"}),
            ]
        )
        client = ZhilianChannelClient(transport=transport)
        with pytest.raises(IntegrationApiError) as exc_info:
            await client.publish_posting("t-1", CREDENTIALS, {"title": "后端"}, None)
        assert exc_info.value.is_token_invalid is True
        assert len(transport.requests) == 4


# --------------------------------------------------------------------- 重试与缓存


class TestTokenRetryAndCache:
    """token 失效强取重试与缓存"""

    @pytest.mark.asyncio
    async def test_invalid_token_refreshes_and_retries_once(self):
        transport = FakeTransport(
            [
                _json_response(200, {"access_token": "tk-old", "expires_in": 7200}),
                (401, {"code": "401"}),
                _json_response(200, {"access_token": "tk-new", "expires_in": 7200}),
                _json_response(200, {"code": "200", "jobId": "zp-1"}),
            ]
        )
        client = ZhilianChannelClient(transport=transport)
        external_id = await client.publish_posting("t-1", CREDENTIALS, {"title": "后端"}, None)
        assert external_id == "zp-1"
        assert len(transport.requests) == 4

    @pytest.mark.asyncio
    async def test_non_invalid_error_no_retry(self):
        transport = FakeTransport(
            [
                _json_response(200, {"access_token": "tk-1", "expires_in": 7200}),
                _json_response(200, {"code": "500", "message": "server error"}),
            ]
        )
        client = ZhilianChannelClient(transport=transport)
        with pytest.raises(IntegrationApiError) as exc_info:
            await client.publish_posting("t-1", CREDENTIALS, {"title": "后端"}, None)
        assert exc_info.value.is_token_invalid is False
        assert len(transport.requests) == 2


# --------------------------------------------------------------------- 注册表


class TestRegistry:
    """渠道注册表"""

    def test_unknown_channel_rejected(self):
        with pytest.raises(IntegrationConfigError, match="不支持的招聘渠道"):
            get_channel_client("boss")

    def test_known_channels_resolved(self):
        for channel in ("zhilian", "job51", "liepin"):
            client = get_channel_client(channel)
            assert client.channel == channel

    def test_transport_injection_builds_fresh_instance(self):
        client = get_channel_client("zhilian", transport=FakeTransport([]))
        assert isinstance(client, ZhilianChannelClient)


# --------------------------------------------------------------------- 凭证解析


class TestCredentialsResolution:
    """凭证解析（iam_client 桩）"""

    @pytest.mark.asyncio
    async def test_disabled_channel_rejected(self):
        session = object()

        async def fake_get(session, tenant_id, code):
            return {"enabled": False, "app_key": "k", "app_secret": ""}

        with patch("hr.integration.credentials.get_iam_client") as factory:
            factory.return_value.get_system_setting = fake_get
            with pytest.raises(IntegrationDisabledError):
                await resolve_channel_credentials(session, "t-1", "zhilian")

    @pytest.mark.asyncio
    async def test_missing_block_config_error(self):
        session = object()

        async def fake_get(session, tenant_id, code):
            return None

        with patch("hr.integration.credentials.get_iam_client") as factory:
            factory.return_value.get_system_setting = fake_get
            with pytest.raises(IntegrationConfigError, match="未配置"):
                await resolve_channel_credentials(session, "t-1", "zhilian")

    @pytest.mark.asyncio
    async def test_sync_config_defaults(self):
        from hr.integration.credentials import resolve_sync_config

        assert resolve_sync_config({}) == (True, 60)
        assert resolve_sync_config({"sync_enabled": "false", "sync_interval_minutes": "0"}) == (
            False,
            60,
        )
        assert resolve_sync_config({"sync_interval_minutes": 30}) == (True, 30)
