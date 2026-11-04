"""招聘渠道服务：状态总览 / 手动同步任务化 / 定时与 webhook 归集编排

归集统一走 candidate_service.collect_application（幂等 upsert + 合并建议），
AI 解析与通知失败均不阻断归集主流程。
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.cache.redis_util import RedisUtil
from framework.clients.iam_client import get_iam_client
from framework.common.exceptions import BadRequestError, NotFoundError
from framework.database.mixins.tenant import skip_tenant_filter
from framework.notification.dispatcher import notify
from framework.tasks.service import task_service
from framework.tenant.context import TenantContext

from hr.integration.credentials import (
    resolve_channel_credentials,
    resolve_sync_config,
)
from hr.integration.errors import (
    IntegrationAuthError,
    IntegrationConfigError,
    IntegrationDisabledError,
    IntegrationError,
)
from hr.integration.providers import get_channel_client
from hr.models import Candidate, JobPosting, JobRequisition
from hr.services.candidate_service import candidate_service

_logger = logger.bind(name=__name__)

SYNC_TASK_TYPE = "hr_channel_sync"
SYNC_QUEUE = "hr-recruiting"

# 渠道展示名（internal 为站内直投渠道，无同步语义不进卡面）
CHANNEL_LABELS: dict[str, str] = {
    "zhilian": "智联招聘",
    "job51": "前程无忧",
    "liepin": "猎聘",
}
SYNC_ENABLED_CHANNELS = tuple(CHANNEL_LABELS)

# 同步统计 Redis（演示实现：最近同步时间与累计归集数存 Redis，非持久台账）
_LAST_SYNC_KEY = "hr:channel:last_sync:{tenant_id}:{channel}"
_COLLECTED_KEY = "hr:channel:collected:{tenant_id}:{channel}"

# webhook 签名头
WEBHOOK_SIGNATURE_HEADER = "X-Hr-Signature"


def _now() -> datetime:
    return datetime.now(UTC)


class ChannelService:
    """招聘渠道业务"""

    # ── 状态总览 ──

    async def list_channels(self, session: AsyncSession, tenant_id: str) -> list[dict]:
        """渠道卡面数据：凭证状态 / 同步开关与间隔 / 累计归集数 / 最近同步。"""
        counts = dict(
            (
                await session.execute(
                    select(Candidate.source_channel, func.count(Candidate.id))
                    .where(Candidate.source_channel.in_(SYNC_ENABLED_CHANNELS))
                    .group_by(Candidate.source_channel)
                )
            ).all()
        )
        channels = []
        for code, label in CHANNEL_LABELS.items():
            config = await self._read_channel_config(session, tenant_id, code)
            channels.append(
                {
                    "channel": code,
                    "name": label,
                    "configured": config is not None,
                    "enabled": bool((config or {}).get("enabled") in (True, "true")),
                    "sync_enabled": bool(
                        (config or {}).get("sync_enabled") in (True, "true")
                    ),
                    "sync_interval_minutes": int(
                        (config or {}).get("sync_interval_minutes") or 60
                    ),
                    "collected_total": int(counts.get(code, 0)),
                    "last_sync_at": await self._get_last_sync(tenant_id, code),
                }
            )
        return channels

    async def _read_channel_config(
        self, session: AsyncSession, tenant_id: str, channel: str
    ) -> dict | None:
        """读原始凭证块（不解密不校验，仅状态展示用）。"""
        try:
            return await get_iam_client().get_system_setting(
                session, tenant_id, f"hr_channel_{channel}"
            )
        except Exception:  # noqa: BLE001 — 块缺失/iam 不可达均视为未配置
            return None

    async def _get_last_sync(self, tenant_id: str, channel: str) -> str | None:
        if not RedisUtil.is_initialized():
            return None
        return await RedisUtil.get(
            _LAST_SYNC_KEY.format(tenant_id=tenant_id, channel=channel)
        )

    async def get_channel_postings(
        self, session: AsyncSession, tenant_id: str, channel: str
    ) -> list[JobPosting]:
        result = await session.execute(
            select(JobPosting).where(
                JobPosting.tenant_id == tenant_id,
                JobPosting.channel == channel,
            )
        )
        return list(result.scalars().all())

    # ── 手动同步（任务化）──

    async def trigger_sync(
        self, session: AsyncSession, tenant_id: str, channel: str
    ) -> str:
        """手动触发候选人拉取（任务化异步执行，返回任务 ID）。"""
        if channel not in SYNC_ENABLED_CHANNELS:
            raise BadRequestError(f"渠道 {channel} 不支持同步")
        result = await task_service.submit(
            session,
            task_type=SYNC_TASK_TYPE,
            queue=SYNC_QUEUE,
            config_snapshot={"tenant_id": tenant_id, "channel": channel},
            resource_type="hr_channel",
            resource_id=channel,
        )
        return str(result.id)

    async def test_connection(
        self, session: AsyncSession, tenant_id: str, channel: str
    ) -> dict:
        """连通测试：解析凭证后向渠道换取 token 验证（fresh 强取不读缓存）。

        配置缺失/未启用与换取失败均返回 ok=False+原因（连通测试语义，
        不以 5xx 表达业务失败）。
        """
        if channel not in SYNC_ENABLED_CHANNELS:
            raise BadRequestError(f"渠道 {channel} 不支持连通测试")
        try:
            credentials = await resolve_channel_credentials(session, tenant_id, channel)
        except (IntegrationConfigError, IntegrationDisabledError) as exc:
            return {"channel": channel, "ok": False, "message": str(exc)}
        client = get_channel_client(channel)
        try:
            await client.get_token(tenant_id, channel, credentials, fresh=True)
        except IntegrationError as exc:
            return {"channel": channel, "ok": False, "message": str(exc)}
        return {"channel": channel, "ok": True, "message": "凭证有效，渠道连通正常"}

    # ── 归集编排（定时任务 / 手动任务 / webhook 共用）──

    async def sync_channel(
        self, session: AsyncSession, tenant_id: str, channel: str
    ) -> dict:
        """拉取渠道投递并归集入库（幂等），返回统计与合并建议。

        凭证未配置/渠道停用直接返回 skipped（定时扫描场景常态，不视为失败）。
        """
        try:
            credentials = await resolve_channel_credentials(session, tenant_id, channel)
        except (IntegrationConfigError, IntegrationDisabledError) as exc:
            _logger.info(f"渠道 {channel} 同步跳过: {exc}")
            return {"channel": channel, "skipped": True, "reason": str(exc)}

        client = get_channel_client(channel)
        postings = await self.get_channel_postings(session, tenant_id, channel)
        stat = {"channel": channel, "fetched": 0, "new": 0, "duplicates": 0, "suggestions": []}
        for posting in postings:
            if posting.status != "published":
                continue
            applications = await client.fetch_applications(
                tenant_id,
                credentials,
                posting.external_post_id or str(posting.id),
            )
            for item in applications:
                stat["fetched"] += 1
                _, suggestion, is_new = await candidate_service.collect_application(
                    session,
                    channel=channel,
                    external_candidate_id=item.external_candidate_id,
                    external_application_id=item.external_application_id,
                    requisition_id=str(posting.requisition_id),
                    name=item.name,
                    phone=item.phone,
                    email=item.email,
                    resume_url=item.resume_url,
                    resume_text=item.resume_text,
                    apply_time=self._parse_apply_time(item.apply_time),
                )
                if is_new:
                    stat["new"] += 1
                if suggestion:
                    stat["suggestions"].append(suggestion)

        await self._touch_sync_stat(tenant_id, channel, stat)
        await self._notify_managers(session, tenant_id, channel, postings, stat)
        return stat

    @staticmethod
    def _parse_apply_time(raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None

    async def _touch_sync_stat(
        self, tenant_id: str, channel: str, stat: dict
    ) -> None:
        if not RedisUtil.is_initialized():
            return
        await RedisUtil.set(
            _LAST_SYNC_KEY.format(tenant_id=tenant_id, channel=channel),
            _now().isoformat(),
        )
        if stat.get("new"):
            key = _COLLECTED_KEY.format(tenant_id=tenant_id, channel=channel)
            total = int(await RedisUtil.get(key) or 0) + stat["new"]
            await RedisUtil.set(key, total)

    async def _notify_managers(
        self,
        session: AsyncSession,
        tenant_id: str,
        channel: str,
        postings: list[JobPosting],
        stat: dict,
    ) -> None:
        """新归集通知用人经理（需求创建人）；失败不阻断归集。"""
        new_count = stat.get("new") or 0
        if not new_count:
            return
        requisition_ids = {str(p.requisition_id) for p in postings}
        try:
            result = await session.execute(
                select(JobRequisition).where(
                    JobRequisition.id.in_(requisition_ids),
                    JobRequisition.created_by.isnot(None),
                )
            )
            recipients = {
                r.created_by for r in result.scalars().all() if r.created_by
            }
            if not recipients:
                return
            label = CHANNEL_LABELS.get(channel, channel)
            await notify(
                session=session,
                notification_type="hr_channel_collected",
                recipients=sorted(recipients),
                title=f"{label} 新增 {new_count} 份投递",
                content=f"渠道「{label}」本次同步新归集 {new_count} 份候选人投递，请及时处理初筛。",
                link="/hr/candidates",
                tenant_id=tenant_id,
            )
        except Exception as exc:  # noqa: BLE001 — 通知失败不阻断归集
            _logger.warning(f"渠道归集通知失败 channel={channel}: {exc}")

    # ── webhook 接收 ──

    async def handle_webhook(
        self,
        session: AsyncSession,
        channel: str,
        *,
        raw_body: bytes,
        signature: str | None,
    ) -> dict:
        """渠道投递事件接收：HMAC-SHA256(app_secret, body) 验签后归集入库。

        webhook 无租户上下文——按 payload.post_id 跨租户定位发布记录取
        tenant_id 并绑定上下文；签名不符抛 IntegrationAuthError（控制器转 401）。
        """
        if channel not in SYNC_ENABLED_CHANNELS:
            raise NotFoundError(f"未知渠道 {channel}")
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise BadRequestError("webhook 请求体非法 JSON") from exc
        if payload.get("event") not in (None, "application.created"):
            return {"accepted": True, "handled": False}

        posting = await self._find_posting_by_external(
            session, channel, str(payload.get("post_id") or "")
        )
        if posting is None:
            raise NotFoundError("webhook 投递未匹配到已发布职位")
        tenant_id = str(posting.tenant_id)
        TenantContext.set_tenant_id(tenant_id)

        credentials = await resolve_channel_credentials(session, tenant_id, channel)
        expected = hmac.new(
            credentials["app_secret"].encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not signature or not hmac.compare_digest(expected, signature.strip().lower()):
            raise IntegrationAuthError("webhook 签名校验失败")

        candidate = payload.get("candidate") or {}
        application, suggestion, is_new = await candidate_service.collect_application(
            session,
            channel=channel,
            external_candidate_id=str(candidate.get("external_id") or ""),
            external_application_id=payload.get("application_id"),
            requisition_id=str(posting.requisition_id),
            name=candidate.get("name"),
            phone=candidate.get("phone"),
            email=candidate.get("email"),
            resume_url=candidate.get("resume_url"),
            resume_text=candidate.get("resume_text"),
            apply_time=self._parse_apply_time(payload.get("applied_at")),
        )
        return {
            "accepted": True,
            "handled": True,
            "is_new": is_new,
            "application_id": str(application.id),
            "suggestion": suggestion,
        }

    async def _find_posting_by_external(
        self, session: AsyncSession, channel: str, external_post_id: str
    ) -> JobPosting | None:
        if not external_post_id:
            return None
        with skip_tenant_filter():
            result = await session.execute(
                select(JobPosting).where(
                    JobPosting.channel == channel,
                    JobPosting.external_post_id == external_post_id,
                    JobPosting.status == "published",
                )
            )
            return result.scalar_one_or_none()


channel_service = ChannelService()
