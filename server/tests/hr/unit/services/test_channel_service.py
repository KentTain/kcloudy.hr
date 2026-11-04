"""渠道服务单元测试

覆盖：渠道状态总览（凭证配置/累计归集数）、同步编排（未配置跳过/归集
统计/合并建议聚合）、webhook 验签（签名不符拒绝/正常入库）、
LLM 解析输出容错 JSON 提取。
"""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError
from framework.tenant.context import TenantContext

from hr.integration.errors import IntegrationAuthError, IntegrationDisabledError
from hr.integration.providers.base import ChannelApplication
from hr.models import JobPosting
from hr.services.candidate_service import CandidateService
from hr.services.channel_service import ChannelService


class _FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one_or_none(self):
        if self._scalar is not None:
            return self._scalar
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


def _mock_session(execute_results=None) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(
        side_effect=list(execute_results) if execute_results else []
    )
    session.commit = AsyncMock()
    return session


@pytest.fixture(autouse=True)
def _redis_off():
    with patch("hr.services.channel_service.RedisUtil") as redis:
        redis.is_initialized.return_value = False
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()
        redis.delete = AsyncMock()
        yield redis


# --------------------------------------------------------------------- 状态总览


class TestListChannels:
    """渠道卡面状态"""

    @pytest.mark.asyncio
    async def test_channel_status_snapshot(self):
        counts = _FakeResult(rows=[("zhilian", 5)])
        session = _mock_session(execute_results=[counts])
        config = {
            "enabled": "true",
            "app_key": "k",
            "app_secret": "s",
            "sync_enabled": "true",
            "sync_interval_minutes": "30",
        }
        with patch(
            "hr.services.channel_service.get_iam_client"
        ) as iam_factory:
            iam = iam_factory.return_value
            iam.get_system_setting = AsyncMock(
                side_effect=lambda _s, _t, code: config
                if code == "hr_channel_zhilian"
                else None
            )
            channels = await ChannelService().list_channels(session, "t-1")
        by_code = {c["channel"]: c for c in channels}
        assert set(by_code) == {"zhilian", "job51", "liepin"}
        assert by_code["zhilian"]["configured"] is True
        assert by_code["zhilian"]["enabled"] is True
        assert by_code["zhilian"]["sync_interval_minutes"] == 30
        assert by_code["zhilian"]["collected_total"] == 5
        assert by_code["job51"]["configured"] is False
        assert by_code["job51"]["collected_total"] == 0


# --------------------------------------------------------------------- 同步编排


def _channel_app(ext_id: str) -> ChannelApplication:
    return ChannelApplication(
        external_application_id=f"ea-{ext_id}",
        external_candidate_id=f"ec-{ext_id}",
        name=f"候选人{ext_id}",
    )


class TestSyncChannel:
    """归集编排"""

    @pytest.mark.asyncio
    async def test_skips_when_channel_disabled(self):
        session = _mock_session()
        with patch(
            "hr.services.channel_service.resolve_channel_credentials",
            new=AsyncMock(side_effect=IntegrationDisabledError("渠道未启用")),
        ):
            stat = await ChannelService().sync_channel(session, "t-1", "zhilian")
        assert stat["skipped"] is True

    @pytest.mark.asyncio
    async def test_sync_collects_and_aggregates(self):
        session = _mock_session()
        posting = MagicMock(spec=JobPosting)
        posting.status = "published"
        posting.requisition_id = "req-1"
        posting.external_post_id = "post-1"
        posting.id = "p-1"

        client = MagicMock()
        client.fetch_applications = AsyncMock(
            return_value=[_channel_app("1"), _channel_app("2")]
        )
        suggestion = {"candidate_id": "c1", "target_id": "c2", "matched_by": "phone"}
        collect = AsyncMock(
            side_effect=[
                (MagicMock(id="app-1"), None, True),
                (MagicMock(id="app-2"), suggestion, False),
            ]
        )
        with (
            patch(
                "hr.services.channel_service.resolve_channel_credentials",
                new=AsyncMock(return_value={"app_secret": "s"}),
            ),
            patch(
                "hr.services.channel_service.get_channel_client", return_value=client
            ),
            patch(
                "hr.services.channel_service.ChannelService.get_channel_postings",
                new=AsyncMock(return_value=[posting]),
            ),
            patch(
                "hr.services.channel_service.candidate_service.collect_application",
                new=collect,
            ),
            patch(
                "hr.services.channel_service.ChannelService._touch_sync_stat",
                new=AsyncMock(),
            ),
            patch(
                "hr.services.channel_service.ChannelService._notify_managers",
                new=AsyncMock(),
            ) as notify,
        ):
            stat = await ChannelService().sync_channel(session, "t-1", "zhilian")
        assert stat["fetched"] == 2
        assert stat["new"] == 1
        assert stat["suggestions"] == [suggestion]
        collect.assert_awaited()
        notify.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sync_unpublished_posting_not_fetched(self):
        session = _mock_session()
        posting = MagicMock(spec=JobPosting)
        posting.status = "offline"
        client = MagicMock()
        client.fetch_applications = AsyncMock(return_value=[])
        with (
            patch(
                "hr.services.channel_service.resolve_channel_credentials",
                new=AsyncMock(return_value={"app_secret": "s"}),
            ),
            patch(
                "hr.services.channel_service.get_channel_client", return_value=client
            ),
            patch(
                "hr.services.channel_service.ChannelService.get_channel_postings",
                new=AsyncMock(return_value=[posting]),
            ),
        ):
            stat = await ChannelService().sync_channel(session, "t-1", "zhilian")
        client.fetch_applications.assert_not_awaited()
        assert stat["fetched"] == 0


# --------------------------------------------------------------------- webhook


class TestWebhook:
    """webhook 验签与归集"""

    def _signed(self, secret: str, body: bytes) -> str:
        return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    @pytest.mark.asyncio
    async def test_bad_signature_rejected(self):
        session = _mock_session()
        body = json.dumps({"event": "application.created", "post_id": "p-1"}).encode()
        posting = MagicMock(spec=JobPosting)
        posting.tenant_id = "t-1"
        with (
            patch(
                "hr.services.channel_service.ChannelService._find_posting_by_external",
                new=AsyncMock(return_value=posting),
            ),
            patch(
                "hr.services.channel_service.resolve_channel_credentials",
                new=AsyncMock(return_value={"app_secret": "sec"}),
            ),
        ):
            with pytest.raises(IntegrationAuthError, match="签名校验失败"):
                await ChannelService().handle_webhook(
                    session, "zhilian", raw_body=body, signature="deadbeef"
                )

    @pytest.mark.asyncio
    async def test_valid_signature_collects(self):
        session = _mock_session()
        body = json.dumps(
            {
                "event": "application.created",
                "post_id": "post-1",
                "candidate": {"external_id": "ec-9", "name": "王五"},
            }
        ).encode()
        posting = MagicMock(spec=JobPosting)
        posting.tenant_id = "t-1"
        posting.requisition_id = "req-1"
        collect = AsyncMock(return_value=(MagicMock(id="app-9"), None, True))
        with (
            patch(
                "hr.services.channel_service.ChannelService._find_posting_by_external",
                new=AsyncMock(return_value=posting),
            ),
            patch(
                "hr.services.channel_service.resolve_channel_credentials",
                new=AsyncMock(return_value={"app_secret": "sec"}),
            ),
            patch(
                "hr.services.channel_service.candidate_service.collect_application",
                new=collect,
            ),
        ):
            result = await ChannelService().handle_webhook(
                session,
                "zhilian",
                raw_body=body,
                signature=self._signed("sec", body),
            )
        assert result["handled"] is True
        assert result["is_new"] is True
        assert TenantContext.get_tenant_id() == "t-1"
        collect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_event_accepted_not_handled(self):
        session = _mock_session()
        body = json.dumps({"event": "posting.closed"}).encode()
        result = await ChannelService().handle_webhook(
            session,
            "zhilian",
            raw_body=body,
            signature=None,
        )
        assert result == {"accepted": True, "handled": False}


# --------------------------------------------------------------------- LLM 输出解析


class TestExtractJson:
    """简历解析输出容错"""

    def test_plain_json(self):
        from hr.listeners.services.queue.recruiting_consumers import (
            ResumeParseConsumer,
        )

        assert ResumeParseConsumer._extract_json('{"name": "张三"}') == {"name": "张三"}

    def test_markdown_fence(self):
        from hr.listeners.services.queue.recruiting_consumers import (
            ResumeParseConsumer,
        )

        text = "```json\n{\"skills\": [\"Python\"]}\n```"
        assert ResumeParseConsumer._extract_json(text) == {"skills": ["Python"]}

    def test_surrounding_noise(self):
        from hr.listeners.services.queue.recruiting_consumers import (
            ResumeParseConsumer,
        )

        text = '解析结果如下：{"years": 5} 以上。'
        assert ResumeParseConsumer._extract_json(text) == {"years": 5}

    def test_non_json_raises(self):
        from hr.listeners.services.queue.recruiting_consumers import (
            ResumeParseConsumer,
        )

        with pytest.raises(ValueError, match="非 JSON"):
            ResumeParseConsumer._extract_json("抱歉，我无法解析该简历。")


class TestTestConnection:
    """连通测试：换 token 验证凭证"""

    @pytest.mark.asyncio
    async def test_unsupported_channel_rejected(self):
        with pytest.raises(BadRequestError, match="不支持连通测试"):
            await ChannelService().test_connection(_mock_session(), "t-1", "internal")

    @pytest.mark.asyncio
    async def test_config_missing_returns_not_ok(self):
        session = _mock_session()
        with patch(
            "hr.services.channel_service.resolve_channel_credentials",
            new=AsyncMock(side_effect=IntegrationDisabledError("渠道未启用")),
        ):
            result = await ChannelService().test_connection(session, "t-1", "zhilian")
        assert result["ok"] is False
        assert "未启用" in result["message"]

    @pytest.mark.asyncio
    async def test_token_failure_returns_not_ok(self):
        session = _mock_session()
        client = MagicMock()
        client.get_token = AsyncMock(side_effect=IntegrationAuthError("token 获取失败"))
        with (
            patch(
                "hr.services.channel_service.resolve_channel_credentials",
                new=AsyncMock(return_value={"app_secret": "s"}),
            ),
            patch(
                "hr.services.channel_service.get_channel_client", return_value=client
            ),
        ):
            result = await ChannelService().test_connection(session, "t-1", "zhilian")
        assert result["ok"] is False
        client.get_token.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_success_with_fresh_token(self):
        session = _mock_session()
        client = MagicMock()
        client.get_token = AsyncMock(return_value="tok")
        with (
            patch(
                "hr.services.channel_service.resolve_channel_credentials",
                new=AsyncMock(return_value={"app_secret": "s"}),
            ),
            patch(
                "hr.services.channel_service.get_channel_client", return_value=client
            ),
        ):
            result = await ChannelService().test_connection(session, "t-1", "zhilian")
        assert result == {
            "channel": "zhilian",
            "ok": True,
            "message": "凭证有效，渠道连通正常",
        }
        assert client.get_token.await_args.kwargs["fresh"] is True
