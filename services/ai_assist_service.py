"""AI 助手服务（JD 智能生成 / 面试智能追问）

生成式即时能力：llm_chat 即时返回、不落库；LLM 失败抛业务异常由调用方
降级为「提示手动填写」，原有手动编辑路径不受影响。
"""

from __future__ import annotations

import json

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, NotFoundError

from hr.integration.llm_client import llm_chat
from hr.models import Candidate, CandidateApplication, Interview, JobRequisition
from hr.services.interview_service import interview_service
from sqlalchemy import select

_logger = logger.bind(name=__name__)


class AiAssistService:
    """生成式 AI 助手（草稿即用不落库）"""

    async def generate_jd_draft(
        self, session: AsyncSession, requisition_id: str
    ) -> dict:
        """JD 草稿生成：以岗位/职级/薪酬区间/既有描述为输入；返回即用文本。"""
        requisition = await session.get(JobRequisition, requisition_id)
        if not requisition:
            raise NotFoundError(f"招聘需求 {requisition_id} 不存在")

        salary = "未填写"
        if requisition.salary_min is not None or requisition.salary_max is not None:
            salary = f"{requisition.salary_min or '?'} - {requisition.salary_max or '?'} 元/月"
        prompt = (
            f"职位名称：{requisition.title}\n"
            f"要求职级：{requisition.job_level or '未定'}\n"
            f"招聘人数：{requisition.headcount}\n"
            f"薪酬区间：{salary}\n"
            f"既有描述：{requisition.jd or '（无，从零起草）'}"
        )
        content = await llm_chat(
            self._tenant_id(),
            [
                {
                    "role": "system",
                    "content": (
                        "你是资深招聘 JD 撰写助手。根据给定信息输出完整中文 JD，"
                        "包含「岗位职责」与「任职要求」两节，条目化表述，"
                        "600 字以内。只输出 JD 正文，不要额外解释。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        return {"jd_draft": content.strip()}

    async def generate_followup_questions(
        self, session: AsyncSession, interview_id: str
    ) -> dict:
        """面试追问建议：以候选人简历摘要 + 需求 JD + 轮次为输入；返回建议清单。"""
        interview = await interview_service.get_interview(session, interview_id)
        row = (
            await session.execute(
                select(CandidateApplication, Candidate, JobRequisition)
                .join(Candidate, CandidateApplication.candidate_id == Candidate.id)
                .join(
                    JobRequisition,
                    CandidateApplication.requisition_id == JobRequisition.id,
                )
                .where(CandidateApplication.id == interview.application_id)
            )
        ).first()
        if row is None:
            raise NotFoundError("面试关联投递不存在")
        application, candidate, requisition = row

        profile = candidate.profile or {}
        resume = str(profile.get("resume_raw") or "")[:2000]
        prompt = (
            f"候选人简历摘要：{resume or '（无）'}\n"
            f"应聘岗位：{requisition.title}\n"
            f"岗位 JD：{(requisition.jd or '（无）')[:1500]}\n"
            f"面试轮次：第 {interview.round} 轮\n"
            f"已有反馈：{interview.feedback or '（无）'}"
        )
        content = await llm_chat(
            self._tenant_id(),
            [
                {
                    "role": "system",
                    "content": (
                        "你是面试官助手。基于候选人简历与岗位 JD，输出 3-5 个"
                        "针对性追问问题（重点考察简历疑点与岗位关键能力），"
                        '仅输出 JSON 数组，每项为字符串，如 ["问题1", "问题2"]。'
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        return {"questions": self._parse_questions(content)}

    @staticmethod
    def _parse_questions(content: str) -> list[str]:
        """LLM 输出 JSON 数组解析；容忍 ```json 包裹与纯行文本。"""
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        try:
            payload = json.loads(text)
            if isinstance(payload, list):
                return [str(item) for item in payload if str(item).strip()]
        except json.JSONDecodeError:
            lines = [
                line.lstrip(" 0123456789.-、）) ").strip()
                for line in text.splitlines()
                if line.strip()
            ]
            return [line for line in lines if line][:5]
        raise BadRequestError("追问建议解析失败，请重试或手动填写")

    @staticmethod
    def _tenant_id() -> str:
        from framework.common.ctx import get_tenant_id

        tenant_id = get_tenant_id()
        if not tenant_id:
            raise BadRequestError("缺少租户上下文")
        return tenant_id


ai_assist_service = AiAssistService()
