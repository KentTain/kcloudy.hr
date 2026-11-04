"""面试服务单元测试

覆盖：轮次自动 +1（终态拒绝安排）、结论通过自动流转拟录用（失败不阻断）、
改期通知面试官（失败不阻断）、周视图按日分组。
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ConflictError
from framework.tenant.context import TenantContext

from hr.models import Candidate, CandidateApplication, Interview, JobRequisition
from hr.schemas.recruiting import InterviewCreate, InterviewUpdate
from hr.services.interview_service import InterviewService


class _FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one(self):
        if self._scalar is not None:
            return self._scalar
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        if self._scalar is not None:
            return self._scalar
        return self._rows[0] if self._rows else None

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


def _mock_session(get_map=None, execute_results=None) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.flush = AsyncMock()
    added: list = []
    session.add = MagicMock(side_effect=added.append)
    session._added = added

    async def _get(model, pk):
        return (get_map or {}).get((model.__name__, str(pk)))

    session.get = AsyncMock(side_effect=_get)
    session.execute = AsyncMock(
        side_effect=list(execute_results) if execute_results else []
    )
    return session


def _application(**overrides) -> CandidateApplication:
    defaults = dict(
        id="app-1",
        tenant_id="t-1",
        candidate_id="cand-1",
        requisition_id="req-1",
        stage="interviewing",
        stage_history=[],
        apply_time=datetime.now(UTC),
    )
    defaults.update(overrides)
    return CandidateApplication(**defaults)


def _candidate() -> Candidate:
    return Candidate(
        id="cand-1", tenant_id="t-1", name="张三", source_channel="zhilian"
    )


def _requisition() -> JobRequisition:
    return JobRequisition(
        id="req-1",
        tenant_id="t-1",
        req_no="REQ001",
        title="Python 工程师",
        org_id="org-1",
        headcount=2,
        priority="medium",
        status="recruiting",
        filled_count=0,
    )


@pytest.fixture(autouse=True)
def _tenant_context():
    TenantContext.set_tenant_id("t-1")
    yield
    TenantContext.clear()


class TestCreateInterview:
    """安排面试"""

    @pytest.mark.asyncio
    async def test_round_auto_increment(self):
        application = _application()
        session = _mock_session(
            get_map={("CandidateApplication", "app-1"): application},
            execute_results=[_FakeResult(scalar=2)],
        )
        data = InterviewCreate(
            application_id="app-1",
            interviewer_id="emp-9",
            scheduled_at=datetime.now(UTC) + timedelta(days=1),
        )
        interview = await InterviewService().create_interview(session, data)
        assert interview.round == 3
        assert any(i is interview for i in session._added)

    @pytest.mark.asyncio
    async def test_terminal_application_rejected(self):
        application = _application(stage="rejected")
        session = _mock_session(
            get_map={("CandidateApplication", "app-1"): application}
        )
        data = InterviewCreate(
            application_id="app-1",
            interviewer_id="emp-9",
            scheduled_at=datetime.now(UTC) + timedelta(days=1),
        )
        with pytest.raises(BadRequestError, match="终态"):
            await InterviewService().create_interview(session, data)


class TestUpdateInterview:
    """结论与改期"""

    @pytest.mark.asyncio
    async def test_pass_promotes_to_pre_hire(self):
        interview = Interview(
            id="iv-1",
            tenant_id="t-1",
            application_id="app-1",
            round=1,
            interviewer_id="emp-9",
            scheduled_at=datetime.now(UTC),
            interview_form="onsite",
            result="pending",
        )
        session = _mock_session(
            get_map={("Interview", "iv-1"): interview},
            execute_results=[_FakeResult(rows=[_application()])],
        )
        with patch(
            "hr.services.interview_service.candidate_service.change_stage",
            new=AsyncMock(),
        ) as change_stage:
            result = await InterviewService().update_interview(
                session, "iv-1", InterviewUpdate(result="pass", feedback="不错")
            )
        assert result.result == "pass"
        assert result.feedback == "不错"
        change_stage.assert_awaited_once()
        assert change_stage.await_args.args[2] == "pre_hire"

    @pytest.mark.asyncio
    async def test_pass_promotion_failure_does_not_block(self):
        interview = Interview(
            id="iv-1",
            tenant_id="t-1",
            application_id="app-1",
            round=1,
            interviewer_id="emp-9",
            scheduled_at=datetime.now(UTC),
            interview_form="onsite",
            result="pending",
        )
        session = _mock_session(
            get_map={("Interview", "iv-1"): interview},
            execute_results=[_FakeResult(rows=[_application()])],
        )
        with patch(
            "hr.services.interview_service.candidate_service.change_stage",
            new=AsyncMock(side_effect=ConflictError("需求已关闭")),
        ):
            result = await InterviewService().update_interview(
                session, "iv-1", InterviewUpdate(result="pass")
            )
        assert result.result == "pass"

    @pytest.mark.asyncio
    async def test_fail_does_not_promote(self):
        interview = Interview(
            id="iv-1",
            tenant_id="t-1",
            application_id="app-1",
            round=1,
            interviewer_id="emp-9",
            scheduled_at=datetime.now(UTC),
            interview_form="onsite",
            result="pending",
        )
        session = _mock_session(get_map={("Interview", "iv-1"): interview})
        with patch(
            "hr.services.interview_service.candidate_service.change_stage",
            new=AsyncMock(),
        ) as change_stage:
            await InterviewService().update_interview(
                session, "iv-1", InterviewUpdate(result="fail")
            )
        change_stage.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reschedule_notifies_interviewer(self):
        from datetime import timezone

        interview = Interview(
            id="iv-1",
            tenant_id="t-1",
            application_id="app-1",
            round=1,
            interviewer_id="emp-9",
            scheduled_at=datetime(2026, 10, 20, 10, 0, tzinfo=UTC),
            interview_form="onsite",
            result="pending",
        )
        interviewer = MagicMock()
        interviewer.user_id = "u-9"
        session = _mock_session(
            get_map={
                ("Interview", "iv-1"): interview,
                ("Employee", "emp-9"): interviewer,
            }
        )
        new_time = datetime(2026, 10, 22, 14, 0, tzinfo=timezone.utc)
        with patch(
            "hr.services.interview_service.notify", new=AsyncMock()
        ) as notify:
            await InterviewService().update_interview(
                session, "iv-1", InterviewUpdate(scheduled_at=new_time)
            )
        notify.assert_awaited_once()
        assert notify.await_args.kwargs["recipients"] == ["u-9"]

    @pytest.mark.asyncio
    async def test_reschedule_notification_failure_does_not_block(self):
        interview = Interview(
            id="iv-1",
            tenant_id="t-1",
            application_id="app-1",
            round=1,
            interviewer_id="emp-9",
            scheduled_at=datetime(2026, 10, 20, 10, 0, tzinfo=UTC),
            interview_form="onsite",
            result="pending",
        )
        interviewer = MagicMock()
        interviewer.user_id = "u-9"
        session = _mock_session(
            get_map={
                ("Interview", "iv-1"): interview,
                ("Employee", "emp-9"): interviewer,
            }
        )
        new_time = datetime(2026, 10, 22, 14, 0, tzinfo=UTC)
        with patch(
            "hr.services.interview_service.notify",
            new=AsyncMock(side_effect=RuntimeError("通知服务不可用")),
        ):
            result = await InterviewService().update_interview(
                session, "iv-1", InterviewUpdate(scheduled_at=new_time)
            )
        assert result.scheduled_at == new_time


class TestWeeklyView:
    """周视图"""

    @pytest.mark.asyncio
    async def test_groups_by_day(self):
        day1 = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)
        day2 = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)
        iv1 = Interview(
            id="iv-1", tenant_id="t-1", application_id="app-1", round=1,
            interviewer_id="emp-9", scheduled_at=day1, interview_form="onsite",
            result="pending",
        )
        iv2 = Interview(
            id="iv-2", tenant_id="t-1", application_id="app-1", round=2,
            interviewer_id="emp-8", scheduled_at=day2, interview_form="video",
            result="pending",
        )
        app, cand, req = _application(), _candidate(), _requisition()
        session = _mock_session(execute_results=[_FakeResult(rows=[
            (iv1, app, cand, req),
            (iv2, app, cand, req),
        ])])
        weekly = await InterviewService().get_weekly(session, start=date(2026, 10, 19))
        assert weekly["start"] == "2026-10-19"
        assert len(weekly["days"]["2026-10-19"]) == 1
        assert len(weekly["days"]["2026-10-21"]) == 1
        assert weekly["days"]["2026-10-20"] == []
        assert weekly["days"]["2026-10-19"][0]["candidate_name"] == "张三"


class TestSummaryTask:
    """纪要任务化提交（幂等 + 消费者回写链路的服务侧）"""

    @pytest.mark.asyncio
    async def test_submits_task_when_no_active(self):
        TenantContext.set_tenant_id("t-1")
        interview = Interview(
            id="itv-1", tenant_id="t-1", application_id="app-1", round=1,
            interviewer_id="emp-1", scheduled_at=datetime.now(UTC),
            interview_form="onsite", result="pending",
        )
        session = _mock_session(
            get_map={("Interview", "itv-1"): interview},
            execute_results=[_FakeResult(rows=[])],  # 无进行中任务
        )
        _task = MagicMock()
        _task.id = "task-9"
        with patch(
            "framework.tasks.service.task_service.submit",
            new=AsyncMock(return_value=_task),
        ) as submit:
            result = await InterviewService().submit_summary_task(session, "itv-1")
        submit.assert_awaited_once()
        kwargs = submit.await_args.kwargs
        assert kwargs["queue"] == "hr-interview-summary"
        assert kwargs["config_snapshot"]["interview_id"] == "itv-1"
        assert result == {"task_id": "task-9", "duplicated": False}

    @pytest.mark.asyncio
    async def test_active_task_returns_existing_idempotent(self):
        TenantContext.set_tenant_id("t-1")
        interview = Interview(
            id="itv-1", tenant_id="t-1", application_id="app-1", round=1,
            interviewer_id="emp-1", scheduled_at=datetime.now(UTC),
            interview_form="onsite", result="pending",
        )
        session = _mock_session(
            get_map={("Interview", "itv-1"): interview},
            execute_results=[_FakeResult(scalar="task-existing")],
        )
        with patch(
            "framework.tasks.service.task_service.submit",
            new=AsyncMock(),
        ) as submit:
            result = await InterviewService().submit_summary_task(session, "itv-1")
        submit.assert_not_awaited()
        assert result == {"task_id": "task-existing", "duplicated": True}

    @pytest.mark.asyncio
    async def test_generate_summary_writes_back(self):
        TenantContext.set_tenant_id("t-1")
        interview = Interview(
            id="itv-1", tenant_id="t-1", application_id="app-1", round=1,
            interviewer_id="emp-1", scheduled_at=datetime.now(UTC),
            interview_form="onsite", result="pending", feedback="表达清晰",
        )
        session = _mock_session(
            get_map={("Interview", "itv-1"): interview},
            execute_results=[_FakeResult(rows=[(_application(), _candidate(), _requisition())])],
        )
        with patch(
            "hr.services.interview_service.llm_chat",
            new=AsyncMock(return_value="纪要：候选人表达清晰，建议进入下一轮。"),
        ):
            updated = await InterviewService().generate_ai_summary(session, "itv-1")
        assert updated.ai_summary == "纪要：候选人表达清晰，建议进入下一轮。"
