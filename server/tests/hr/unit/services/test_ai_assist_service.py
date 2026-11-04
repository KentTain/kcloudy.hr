"""AI 助手服务单元测试

覆盖：JD 草稿生成（输入组装与 llm 桩）、面试追问建议（JSON/fence/纯文本容错
解析）、LLM 失败异常透传（由调用方降级手动填写）、不落库。
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import NotFoundError
from framework.tenant.context import TenantContext

from hr.models import Candidate, CandidateApplication, Interview, JobRequisition
from hr.services.ai_assist_service import ai_assist_service


def _mock_session(get_map=None) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)

    async def _get(model, pk):
        return (get_map or {}).get((model.__name__, str(pk)))

    session.get = AsyncMock(side_effect=_get)
    return session


def _requisition(**overrides) -> JobRequisition:
    defaults = dict(
        id="req-1",
        tenant_id="t-1",
        req_no="REQ001",
        title="Python 工程师",
        org_id="org-1",
        headcount=2,
        job_level="P6",
        salary_min=20000,
        salary_max=30000,
        jd="旧描述",
    )
    defaults.update(overrides)
    return JobRequisition(**defaults)


def _interview(application_id="app-1", feedback="沟通顺畅") -> Interview:
    return Interview(
        id="itv-1",
        tenant_id="t-1",
        application_id=application_id,
        round=2,
        interviewer_id="emp-1",
        scheduled_at=datetime.now(UTC),
        interview_form="onsite",
        feedback=feedback,
    )


class TestJdDraft:
    """JD 智能生成（不落库）"""

    @pytest.mark.asyncio
    async def test_generates_draft_from_requisition(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session({("JobRequisition", "req-1"): _requisition()})
        with patch(
            "hr.services.ai_assist_service.llm_chat",
            new=AsyncMock(return_value="## 岗位职责\n1. xxx\n## 任职要求\n1. yyy"),
        ) as llm:
            result = await ai_assist_service.generate_jd_draft(session, "req-1")
        prompt = llm.await_args.args[1][1]["content"]
        assert "Python 工程师" in prompt
        assert "P6" in prompt
        assert "20000 - 30000" in prompt
        assert result["jd_draft"].startswith("## 岗位职责")
        # 不落库：草稿生成不写库
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_requisition_not_found(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session()
        with pytest.raises(NotFoundError):
            await ai_assist_service.generate_jd_draft(session, "req-404")

    @pytest.mark.asyncio
    async def test_llm_failure_propagates(self):
        TenantContext.set_tenant_id("t-1")
        session = _mock_session({("JobRequisition", "req-1"): _requisition()})
        with patch(
            "hr.services.ai_assist_service.llm_chat",
            new=AsyncMock(side_effect=RuntimeError("llm down")),
        ):
            with pytest.raises(RuntimeError, match="llm down"):
                await ai_assist_service.generate_jd_draft(session, "req-1")


class TestFollowupQuestions:
    """面试智能追问（不落库）"""

    @pytest.mark.asyncio
    async def test_parses_json_array(self):
        TenantContext.set_tenant_id("t-1")
        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(
            return_value=AsyncMock(
                first=lambda: (
                    CandidateApplication(id="app-1", candidate_id="cand-1", requisition_id="req-1"),
                    Candidate(id="cand-1", name="张三", profile={"resume_raw": "5 年后端"}),
                    _requisition(),
                )
            )
        )
        with patch(
            "hr.services.ai_assist_service.interview_service.get_interview",
            new=AsyncMock(return_value=_interview()),
        ):
            with patch(
                "hr.services.ai_assist_service.llm_chat",
                new=AsyncMock(return_value='["简历中提到的缓存方案请展开讲讲", "为什么考虑换工作"]'),
            ):
                result = await ai_assist_service.generate_followup_questions(session, "itv-1")
        assert result["questions"] == [
            "简历中提到的缓存方案请展开讲讲",
            "为什么考虑换工作",
        ]
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_parses_fence_and_plain_lines(self):
        fence = ai_assist_service._parse_questions(
            '```json\n["问题一", "问题二"]\n```'
        )
        assert fence == ["问题一", "问题二"]
        plain = ai_assist_service._parse_questions("1. 问题一\n2. 问题二")
        assert plain == ["问题一", "问题二"]
