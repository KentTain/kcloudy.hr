"""招聘渠道能力协议：归一化 VO + 渠道客户端 ABC。

职责切分：hr/integration 只管「怎么调渠道 API」（token/分页/错误归一），
消费方（requisition/candidate/channel service）管领域逻辑（拿什么、怎么入库）。

客户端为无状态单例，方法显式携带 tenant_id（token 缓存键维度）与已解析凭证。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from hr.integration.credentials import (
    cache_token,
    get_cached_token,
    invalidate_token,
)
from hr.integration.errors import (
    IntegrationApiError,
    IntegrationAuthError,
    IntegrationNetworkError,
)


# --------------------------------------------------------------------------- VO


@dataclass(frozen=True)
class ChannelApplication:
    """渠道投递归一化 VO（渠道原始字段差异封闭在 provider 内）。"""

    external_application_id: str
    external_candidate_id: str
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    apply_time: str | None = None
    resume_url: str | None = None
    resume_text: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelResume:
    """渠道简历归一化 VO（content_type：html/text/file_url）。"""

    external_candidate_id: str
    content: str
    content_type: str = "html"
    raw: dict = field(default_factory=dict)


# -------------------------------------------------------------------------- ABC


class RecruitingChannelClient(ABC):
    """招聘渠道客户端四能力。

    posting 参数为统一字段字典（title/org_name/job_level/salary_min/
    salary_max/req_no），渠道差异（分页/签名/字段名）封闭在 provider 内。
    """

    channel: str = ""

    @abstractmethod
    async def _request_token(self, credentials: dict) -> tuple[str, int | None]:
        """向渠道换取 token，返回 (token, expires_in)。"""

    async def _authorized_call(self, tenant_id: str, credentials: dict, call):
        """以渠道 token 执行调用，失效强取重试一次。"""

        async def get_token(fresh: bool) -> str:
            return await self.get_token(tenant_id, self.channel, credentials, fresh=fresh)

        return await call_with_token(tenant_id, self.channel, get_token, call)

    @abstractmethod
    async def publish_posting(
        self, tenant_id: str, credentials: dict, posting: dict, jd: str | None
    ) -> str:
        """发布职位，返回渠道职位映射 external_post_id。"""

    @abstractmethod
    async def offline_posting(
        self, tenant_id: str, credentials: dict, external_post_id: str
    ) -> None:
        """下线已发布职位。"""

    @abstractmethod
    async def fetch_applications(
        self,
        tenant_id: str,
        credentials: dict,
        external_post_id: str,
        since: str | None = None,
        page: int = 1,
    ) -> list[ChannelApplication]:
        """拉取职位投递列表（增量 since，分页在 provider 内消化）。"""

    @abstractmethod
    async def fetch_resume(
        self, tenant_id: str, credentials: dict, external_candidate_id: str
    ) -> ChannelResume:
        """拉取候选人简历原文。"""

    async def get_token(
        self, tenant_id: str, channel: str, credentials: dict, *, fresh: bool = False
    ) -> str:
        """token 获取：缓存优先（fresh 强取），未命中换取并写缓存。"""
        if not fresh:
            cached = await get_cached_token(tenant_id, channel)
            if cached:
                return cached
        try:
            token, expires_in = await self._request_token(credentials)
        except IntegrationNetworkError:
            raise
        except Exception as exc:
            raise IntegrationAuthError(
                f"渠道 {channel} token 获取失败: {exc}"
            ) from exc
        await cache_token(tenant_id, channel, token, expires_in)
        return token


# ----------------------------------------------------------------------- 助手


async def call_with_token(tenant_id, channel, get_token, call):
    """带 token 调用：失效错误（is_token_invalid）时失效缓存强取重试一次。"""
    token = await get_token(False)
    try:
        return await call(token)
    except IntegrationApiError as exc:
        if not exc.is_token_invalid:
            raise
    await invalidate_token(tenant_id, channel)
    return await call(await get_token(True))


def raise_api_error(
    message: str,
    *,
    channel: str,
    endpoint: str,
    code: object = None,
    is_token_invalid: bool = False,
) -> None:
    """构造并抛出 IntegrationApiError 的统一入口。"""
    raise IntegrationApiError(
        message,
        channel=channel,
        endpoint=endpoint,
        code=code,
        is_token_invalid=is_token_invalid,
    )
