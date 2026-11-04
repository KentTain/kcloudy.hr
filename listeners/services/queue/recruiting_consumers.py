"""招聘域任务消费者：渠道职位发布回写 / AI 简历解析

统一走 framework TaskConsumer 骨架（CAS 抢占/超时重试/FAILED 可重试）。
AI 解析失败不阻断归集主流程——任务 FAILED 留存原始简历可重试。
"""

import json

from loguru import logger

from framework.common.exceptions import NotFoundError
from framework.database.dependencies import get_listener_session
from framework.tasks.consumer import TaskConsumer
from framework.tasks.service import TaskContext
from framework.tasks.store_protocol import TaskRecord
from framework.tenant.context import TenantContext

from hr.integration.credentials import resolve_channel_credentials
from hr.integration.llm_client import llm_chat
from hr.integration.providers import get_channel_client
from hr.models import Candidate, JobPosting, JobRequisition
from hr.services.candidate_service import (
    RESUME_PARSE_TASK_TYPE,
    candidate_service,
)
from hr.services.channel_service import SYNC_TASK_TYPE, channel_service
from hr.services.interview_service import (
    AI_SUMMARY_QUEUE,
    AI_SUMMARY_TASK_TYPE,
    interview_service,
)
from hr.services.requisition_service import PUBLISH_TASK_TYPE

_logger = logger.bind(name=__name__)

RECRUITING_QUEUE = "hr-recruiting"


class PostingPublishConsumer(TaskConsumer):
    """渠道职位发布消费者：调渠道发布 API 回写 external_post_id。"""

    task_type = PUBLISH_TASK_TYPE
    queue = RECRUITING_QUEUE
    timeout_seconds = 120

    async def execute(self, task: TaskRecord, ctx: TaskContext) -> None:
        tenant_id = task.config_snapshot.get("tenant_id")
        posting_id = task.config_snapshot.get("posting_id")
        if not tenant_id or not posting_id:
            raise ValueError(f"任务配置缺失 tenant_id/posting_id: {task.config_snapshot}")

        TenantContext.set_tenant_id(str(tenant_id))
        async with get_listener_session() as session:
            posting = await session.get(JobPosting, str(posting_id))
            if posting is None:
                raise NotFoundError(f"职位发布记录 {posting_id} 不存在")
            if posting.status == "published":
                return  # 幂等：已发布直接 ACK
            requisition = await session.get(JobRequisition, posting.requisition_id)
            if requisition is None:
                raise NotFoundError(f"招聘需求 {posting.requisition_id} 不存在")

            credentials = await resolve_channel_credentials(
                session, str(tenant_id), posting.channel
            )
            client = get_channel_client(posting.channel)
            external_post_id = await client.publish_posting(
                str(tenant_id),
                credentials,
                {
                    "title": requisition.title,
                    "job_level": requisition.job_level,
                    "salary_min": float(requisition.salary_min)
                    if requisition.salary_min is not None
                    else None,
                    "salary_max": float(requisition.salary_max)
                    if requisition.salary_max is not None
                    else None,
                    "req_no": requisition.req_no,
                },
                requisition.jd,
            )
            posting.external_post_id = external_post_id
            posting.status = "published"
            await session.commit()
        _logger.info(
            f"职位发布完成 posting={posting_id} channel={posting.channel} "
            f"external_post_id={external_post_id}"
        )


class ChannelSyncConsumer(TaskConsumer):
    """手动同步消费者：执行渠道候选人拉取归集（定时任务控频另一通道）。"""

    task_type = SYNC_TASK_TYPE
    queue = RECRUITING_QUEUE
    timeout_seconds = 300

    async def execute(self, task: TaskRecord, ctx: TaskContext) -> None:
        tenant_id = task.config_snapshot.get("tenant_id")
        channel = task.config_snapshot.get("channel")
        if not tenant_id or not channel:
            raise ValueError(f"任务配置缺失 tenant_id/channel: {task.config_snapshot}")
        TenantContext.set_tenant_id(str(tenant_id))
        async with get_listener_session() as session:
            stat = await channel_service.sync_channel(session, str(tenant_id), str(channel))
            await session.commit()
        _logger.info(
            f"渠道手动同步完成 tenant={tenant_id} channel={channel} "
            f"fetched={stat.get('fetched')} new={stat.get('new')}"
        )


_RESUME_PARSE_PROMPT = (
    "你是 HR 简历解析助手。从下面的简历原文中抽取结构化信息，"
    "只输出一个 JSON 对象（不要 markdown 代码块），字段：\n"
    '{"name": "", "phone": "", "email": "", "years": 0, '
    '"education": [{"school": "", "major": "", "degree": ""}], '
    '"experiences": [{"company": "", "title": "", "summary": ""}], '
    '"skills": [], "highlights": "", "risks": ""}\n'
    "无法识别的字段填空值，不要编造。\n\n简历原文：\n"
)


class ResumeParseConsumer(TaskConsumer):
    """AI 简历解析消费者：LLM 结构化抽取回写 profile（失败可重试）。"""

    task_type = RESUME_PARSE_TASK_TYPE
    queue = RECRUITING_QUEUE
    timeout_seconds = 180

    async def acquire(self, task: TaskRecord) -> bool:
        """无原始简历留存（手工录入）直接跳过。"""
        raw = await self._load_resume_raw(task)
        return bool(raw)

    async def execute(self, task: TaskRecord, ctx: TaskContext) -> None:
        tenant_id = str(task.config_snapshot.get("tenant_id") or ctx.tenant_id)
        candidate_id = str(task.config_snapshot.get("candidate_id") or "")
        if not candidate_id:
            raise ValueError(f"任务配置缺失 candidate_id: {task.config_snapshot}")

        raw = await self._load_resume_raw(task)
        if not raw:
            return
        await ctx.report_progress(30, "LLM 解析中")
        content = await llm_chat(
            tenant_id,
            [
                {"role": "system", "content": "你输出严格的 JSON，不含任何多余文本。"},
                {"role": "user", "content": _RESUME_PARSE_PROMPT + raw},
            ],
        )
        profile = self._extract_json(content)
        await ctx.report_progress(80, "回写归一结果")
        TenantContext.set_tenant_id(tenant_id)
        async with get_listener_session() as session:
            await candidate_service.apply_resume_profile(session, candidate_id, profile)
            await session.commit()
        _logger.info(f"简历解析完成 candidate={candidate_id}")

    async def _load_resume_raw(self, task: TaskRecord) -> str | None:
        tenant_id = task.config_snapshot.get("tenant_id")
        candidate_id = task.config_snapshot.get("candidate_id")
        if not tenant_id or not candidate_id:
            return None
        TenantContext.set_tenant_id(str(tenant_id))
        async with get_listener_session() as session:
            candidate = await session.get(Candidate, str(candidate_id))
            if candidate is None:
                return None
            profile = candidate.profile or {}
            raw = profile.get("resume_raw")
            return str(raw) if raw else None

    @staticmethod
    def _extract_json(content: str) -> dict:
        """容错解析 LLM 输出（容忍 markdown fence 与前后杂文本）。"""
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"LLM 简历解析输出非 JSON: {content[:200]}")
        return json.loads(text[start : end + 1])


class InterviewSummaryConsumer(TaskConsumer):
    """AI 面试纪要消费者：LLM 生成纪要回写 interviews.ai_summary（失败可重试）。"""

    task_type = AI_SUMMARY_TASK_TYPE
    queue = AI_SUMMARY_QUEUE
    timeout_seconds = 180

    async def execute(self, task: TaskRecord, ctx: TaskContext) -> None:
        tenant_id = str(task.config_snapshot.get("tenant_id") or ctx.tenant_id)
        interview_id = str(task.config_snapshot.get("interview_id") or "")
        if not interview_id:
            raise ValueError(f"任务配置缺失 interview_id: {task.config_snapshot}")

        await ctx.report_progress(30, "LLM 生成纪要中")
        TenantContext.set_tenant_id(tenant_id)
        async with get_listener_session() as session:
            await interview_service.generate_ai_summary(session, interview_id)
            await session.commit()
        _logger.info(f"面试纪要生成完成 interview={interview_id}")


posting_publish_consumer = PostingPublishConsumer()
channel_sync_consumer = ChannelSyncConsumer()
resume_parse_consumer = ResumeParseConsumer()
interview_summary_consumer = InterviewSummaryConsumer()


async def setup_recruiting_consumers() -> None:
    """注册招聘域任务消费者（发布回写 / 手动同步 / 简历解析 / 面试纪要）。"""
    await posting_publish_consumer.start()
    await channel_sync_consumer.start()
    await resume_parse_consumer.start()
    await interview_summary_consumer.start()


async def cleanup_recruiting_consumers() -> None:
    await posting_publish_consumer.stop()
    await channel_sync_consumer.stop()
    await resume_parse_consumer.stop()
    await interview_summary_consumer.stop()
