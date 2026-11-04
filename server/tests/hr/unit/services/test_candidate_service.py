"""候选人服务单元测试

覆盖：漏斗状态机（非法流转/终态拒绝/onboarded 入职闭环联动）、手工录入
（联系方式必填/关联需求产生投递）、渠道归集幂等 upsert（external id 命中
复用/手机命中生成合并建议）、合并归并、在面投递删除保护、黑名单、
AI 简历解析任务化与 profile 回写。
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError
from framework.tenant.context import TenantContext

from hr.models import Candidate, CandidateApplication, JobRequisition
from hr.services.candidate_service import CandidateService


# --------------------------------------------------------------------- 桩件


class _FakeResult:
    """execute 结果桩：按需支持 scalar_one_or_none / scalars().all() / first()"""

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

    def first(self):
        return self._rows[0] if self._rows else None


def _candidate(**overrides) -> Candidate:
    defaults = dict(
        id="cand-1",
        tenant_id="t-1",
        name="张三",
        phone="13800001111",
        email=None,
        source_channel="zhilian",
        external_candidate_id="ext-1",
        is_blacklist=False,
    )
    defaults.update(overrides)
    return Candidate(**defaults)


def _requisition(**overrides) -> JobRequisition:
    defaults = dict(
        id="req-1",
        tenant_id="t-1",
        req_no="REQ202610001",
        title="Python 工程师",
        org_id="org-1",
        headcount=3,
        priority="medium",
        status="recruiting",
        filled_count=0,
    )
    defaults.update(overrides)
    return JobRequisition(**defaults)


def _application(**overrides) -> CandidateApplication:
    defaults = dict(
        id="app-1",
        tenant_id="t-1",
        candidate_id="cand-1",
        requisition_id="req-1",
        stage="pending_screening",
        stage_history=[
            {
                "stage": "pending_screening",
                "operator_id": None,
                "operated_at": datetime.now(UTC).isoformat(),
                "remark": None,
            }
        ],
        apply_time=datetime.now(UTC),
    )
    defaults.update(overrides)
    return CandidateApplication(**defaults)


def _mock_session(get_map=None, execute_results=None) -> AsyncMock:
    """session 桩：get 按 (模型类名, 主键) 取值；flush 为新增对象分配 id。"""
    session = AsyncMock(spec=AsyncSession)
    added: list = []
    session.add = MagicMock(side_effect=added.append)

    async def _flush():
        for i, obj in enumerate(added, start=1):
            if getattr(obj, "id", None) is None:
                obj.id = f"gen-{i}"

    session.flush = AsyncMock(side_effect=_flush)
    session.delete = AsyncMock()

    async def _get(model, pk):
        return (get_map or {}).get((model.__name__, str(pk)))

    session.get = AsyncMock(side_effect=_get)
    session.execute = AsyncMock(
        side_effect=list(execute_results) if execute_results else []
    )
    session._added = added
    return session


@pytest.fixture(autouse=True)
def _tenant_context():
    TenantContext.set_tenant_id("t-1")
    yield
    TenantContext.clear()


# --------------------------------------------------------------------- 状态机


class TestChangeStage:
    """漏斗状态机"""

    @pytest.mark.asyncio
    async def test_normal_transition_appends_history(self):
        application = _application(stage="pending_screening")
        session = _mock_session(
            get_map={
                ("CandidateApplication", "app-1"): application,
                ("JobRequisition", "req-1"): _requisition(),
            }
        )
        result = await CandidateService().change_stage(
            session, "app-1", "screening_passed", remark="通过初筛"
        )
        assert result.stage == "screening_passed"
        assert len(result.stage_history) == 2
        assert result.stage_history[-1]["stage"] == "screening_passed"
        assert result.stage_history[-1]["remark"] == "通过初筛"

    @pytest.mark.asyncio
    async def test_illegal_transition_rejected(self):
        application = _application(stage="pending_screening")
        session = _mock_session(get_map={("CandidateApplication", "app-1"): application})
        with pytest.raises(ConflictError, match="不允许流转"):
            await CandidateService().change_stage(session, "app-1", "interviewing")

    @pytest.mark.asyncio
    async def test_terminal_stage_rejected(self):
        application = _application(stage="rejected")
        session = _mock_session(get_map={("CandidateApplication", "app-1"): application})
        with pytest.raises(ConflictError, match="终态"):
            await CandidateService().change_stage(session, "app-1", "pending_screening")

    @pytest.mark.asyncio
    async def test_onboarded_increments_filled_count(self):
        application = _application(stage="pre_onboard")
        requisition = _requisition(status="recruiting", headcount=3, filled_count=1)
        session = _mock_session(
            get_map={
                ("CandidateApplication", "app-1"): application,
                ("JobRequisition", "req-1"): requisition,
            }
        )
        await CandidateService().change_stage(
            session, "app-1", "onboarded", employee_id="emp-1"
        )
        assert application.stage == "onboarded"
        assert application.employee_id == "emp-1"
        assert requisition.filled_count == 2
        assert requisition.status == "partial"

    @pytest.mark.asyncio
    async def test_onboarded_fills_requisition(self):
        application = _application(stage="pre_onboard")
        requisition = _requisition(status="recruiting", headcount=2, filled_count=1)
        session = _mock_session(
            get_map={
                ("CandidateApplication", "app-1"): application,
                ("JobRequisition", "req-1"): requisition,
            }
        )
        await CandidateService().change_stage(session, "app-1", "onboarded")
        assert requisition.status == "filled"

    @pytest.mark.asyncio
    async def test_closed_requisition_blocks_transition(self):
        application = _application(stage="pending_screening")
        session = _mock_session(
            get_map={
                ("CandidateApplication", "app-1"): application,
                ("JobRequisition", "req-1"): _requisition(status="closed"),
            }
        )
        with pytest.raises(ConflictError, match="已关闭"):
            await CandidateService().change_stage(session, "app-1", "screening_passed")

    @pytest.mark.asyncio
    async def test_missing_application_404(self):
        session = _mock_session()
        with pytest.raises(NotFoundError):
            await CandidateService().change_stage(session, "nope", "screening_passed")


# --------------------------------------------------------------------- 手工录入


class TestCreateCandidate:
    """手工录入"""

    @pytest.mark.asyncio
    async def test_requires_phone_or_email(self):
        session = _mock_session()
        with pytest.raises(BadRequestError, match="至少提供一项"):
            await CandidateService().create_candidate(session, name="张三")

    @pytest.mark.asyncio
    async def test_create_with_requisition(self):
        requisition = _requisition()
        session = _mock_session(get_map={("JobRequisition", "req-1"): requisition})
        candidate, application = await CandidateService().create_candidate(
            session,
            name="张三",
            phone="13800001111",
            requisition_id="req-1",
        )
        assert candidate.name == "张三"
        assert candidate.source_channel == "manual"
        assert application is not None
        assert application.stage == "pending_screening"
        assert application.candidate_id == candidate.id
        assert any(a is application for a in session._added)

    @pytest.mark.asyncio
    async def test_create_without_requisition_no_application(self):
        session = _mock_session()
        candidate, application = await CandidateService().create_candidate(
            session, name="张三", email="a@b.c"
        )
        assert application is None

    @pytest.mark.asyncio
    async def test_requisition_not_found(self):
        session = _mock_session()
        with pytest.raises(NotFoundError, match="招聘需求"):
            await CandidateService().create_candidate(
                session, name="张三", phone="13800001111", requisition_id="req-x"
            )

    @pytest.mark.asyncio
    async def test_closed_requisition_rejects_application(self):
        session = _mock_session(
            get_map={("JobRequisition", "req-1"): _requisition(status="closed")}
        )
        with pytest.raises(ConflictError, match="已关闭"):
            await CandidateService().create_candidate(
                session, name="张三", phone="13800001111", requisition_id="req-1"
            )


# --------------------------------------------------------------------- 渠道归集


class TestCollectApplication:
    """渠道归集幂等 upsert"""

    @pytest.mark.asyncio
    async def test_existing_external_id_reuses_candidate(self):
        existing = _candidate()
        requisition = _requisition()
        session = _mock_session(
            execute_results=[_FakeResult(scalar=existing), _FakeResult(scalar=None)],
            get_map={("JobRequisition", "req-1"): requisition},
        )
        application, suggestion, is_new = await CandidateService().collect_application(
            session,
            channel="zhilian",
            external_candidate_id="ext-1",
            external_application_id="ea-1",
            requisition_id="req-1",
            name="张三",
        )
        assert application.candidate_id == "cand-1"
        assert suggestion is None
        assert is_new is True
        # 既有命中不新建候选人档
        assert all(not isinstance(a, Candidate) for a in session._added)

    @pytest.mark.asyncio
    async def test_application_dedup_reuses_existing(self):
        """同候选人同需求重复投递事件：复用既有投递不重投。"""
        existing_app = _application(id="app-exists")
        session = _mock_session(
            execute_results=[
                _FakeResult(scalar=_candidate()),
                _FakeResult(scalar=existing_app),
            ],
        )
        application, suggestion, is_new = await CandidateService().collect_application(
            session,
            channel="zhilian",
            external_candidate_id="ext-1",
            external_application_id="ea-1",
            requisition_id="req-1",
        )
        assert application.id == "app-exists"
        assert is_new is False
        assert all(not isinstance(a, CandidateApplication) for a in session._added)

    @pytest.mark.asyncio
    async def test_new_candidate_phone_match_suggests_merge(self):
        existing = _candidate(id="cand-old", phone="13800001111")
        requisition = _requisition()
        session = _mock_session(
            execute_results=[_FakeResult(scalar=None), _FakeResult(scalar=existing), _FakeResult(scalar=None)],
            get_map={("JobRequisition", "req-1"): requisition},
        )
        application, suggestion, is_new = await CandidateService().collect_application(
            session,
            channel="liepin",
            external_candidate_id="ext-9",
            external_application_id="ea-9",
            requisition_id="req-1",
            name="张三",
            phone="13800001111",
        )
        assert application.stage == "pending_screening"
        assert suggestion is not None
        assert suggestion["candidate_id"] == application.candidate_id
        assert suggestion["target_id"] == "cand-old"
        assert suggestion["matched_by"] == "phone"

    @pytest.mark.asyncio
    async def test_new_candidate_without_match_no_suggestion(self):
        requisition = _requisition()
        session = _mock_session(
            execute_results=[_FakeResult(scalar=None), _FakeResult(scalar=None), _FakeResult(scalar=None)],
            get_map={("JobRequisition", "req-1"): requisition},
        )
        _, suggestion, is_new = await CandidateService().collect_application(
            session,
            channel="job51",
            external_candidate_id="ext-8",
            external_application_id=None,
            requisition_id="req-1",
            name="李四",
        )
        assert suggestion is None

    @pytest.mark.asyncio
    async def test_resume_text_preserved_raw(self):
        requisition = _requisition()
        session = _mock_session(
            execute_results=[_FakeResult(scalar=None), _FakeResult(scalar=None), _FakeResult(scalar=None)],
            get_map={("JobRequisition", "req-1"): requisition},
        )
        _, _, _ = await CandidateService().collect_application(
            session,
            channel="zhilian",
            external_candidate_id="ext-7",
            external_application_id=None,
            requisition_id="req-1",
            resume_text="十年 Python 经验……",
        )
        candidate = next(a for a in session._added if isinstance(a, Candidate))
        assert candidate.profile["resume_raw"].startswith("十年")
        assert candidate.profile["profile_completed"] is False


# --------------------------------------------------------------------- 合并与删除


class TestMergeAndDelete:
    """合并与删除"""

    @pytest.mark.asyncio
    async def test_merge_moves_applications_and_deletes_source(self):
        source = _candidate(id="cand-src")
        apps = [_application(id="app-1"), _application(id="app-2")]
        session = _mock_session(
            get_map={
                ("Candidate", "cand-src"): source,
                ("Candidate", "cand-dst"): _candidate(id="cand-dst"),
            },
            execute_results=[_FakeResult(rows=apps)],
        )
        merged = await CandidateService().merge_candidates(session, "cand-src", "cand-dst")
        assert merged == 2
        assert all(a.candidate_id == "cand-dst" for a in apps)
        session.delete.assert_awaited_once_with(source)

    @pytest.mark.asyncio
    async def test_merge_self_rejected(self):
        session = _mock_session()
        with pytest.raises(BadRequestError, match="自身"):
            await CandidateService().merge_candidates(session, "cand-1", "cand-1")

    @pytest.mark.asyncio
    async def test_delete_blocked_by_active_application(self):
        session = _mock_session(
            get_map={("Candidate", "cand-1"): _candidate()},
            execute_results=[_FakeResult(rows=[("pending_screening",)])],
        )
        with pytest.raises(ConflictError, match="进行中"):
            await CandidateService().delete_candidate(session, "cand-1")
        session.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_success_without_active(self):
        session = _mock_session(
            get_map={("Candidate", "cand-1"): _candidate()},
            execute_results=[_FakeResult(rows=[])],
        )
        await CandidateService().delete_candidate(session, "cand-1")
        session.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_blacklist(self):
        candidate = _candidate(is_blacklist=False)
        session = _mock_session(get_map={("Candidate", "cand-1"): candidate})
        result = await CandidateService().set_blacklist(session, "cand-1", True)
        assert result.is_blacklist is True


# --------------------------------------------------------------------- AI 简历解析


class TestResumeParse:
    """AI 简历解析任务化"""

    @pytest.mark.asyncio
    async def test_trigger_submits_task(self):
        candidate = _candidate()
        session = _mock_session(get_map={("Candidate", "cand-1"): candidate})
        with patch(
            "hr.services.candidate_service.task_service.submit", new=AsyncMock()
        ) as submit:
            await CandidateService().trigger_resume_parse(session, "cand-1")
        submit.assert_awaited_once()
        kwargs = submit.await_args.kwargs
        assert kwargs["task_type"] == "hr_resume_parse"
        assert kwargs["queue"] == "hr-recruiting"
        assert kwargs["config_snapshot"]["candidate_id"] == "cand-1"

    @pytest.mark.asyncio
    async def test_apply_profile_keeps_raw(self):
        candidate = _candidate()
        candidate.profile = {"resume_raw": "原始简历", "profile_completed": False}
        session = _mock_session(get_map={("Candidate", "cand-1"): candidate})
        await CandidateService().apply_resume_profile(
            session, "cand-1", {"skills": ["Python"], "years": 10}
        )
        assert candidate.profile["skills"] == ["Python"]
        assert candidate.profile["profile_completed"] is True
        assert candidate.profile["resume_raw"] == "原始简历"


# --------------------------------------------------------------------- 合并建议


class TestMergeSuggestions:
    """疑似重复档建议（手机/邮箱命中其它候选人）"""

    @pytest.mark.asyncio
    async def test_matched_by_phone_and_email(self):
        candidate = _candidate(email="zhang@example.com")
        dup_phone = _candidate(id="cand-2", name="重名一", email=None)
        dup_email = _candidate(id="cand-3", name="重名二", phone=None)
        session = _mock_session(
            get_map={("Candidate", "cand-1"): candidate},
            execute_results=[_FakeResult(rows=[dup_phone, dup_email])],
        )
        suggestions = await CandidateService().merge_suggestions(session, "cand-1")

        assert [s["candidate_id"] for s in suggestions] == ["cand-2", "cand-3"]
        assert suggestions[0]["matched_by"] == "phone"
        assert suggestions[1]["matched_by"] == "email"
        assert suggestions[0]["name"] == "重名一"

    @pytest.mark.asyncio
    async def test_no_contact_info_returns_empty(self):
        candidate = _candidate(phone=None, email=None)
        session = _mock_session(get_map={("Candidate", "cand-1"): candidate})
        assert await CandidateService().merge_suggestions(session, "cand-1") == []

    @pytest.mark.asyncio
    async def test_candidate_not_found(self):
        session = _mock_session()
        with pytest.raises(NotFoundError, match="候选人"):
            await CandidateService().merge_suggestions(session, "cand-x")
