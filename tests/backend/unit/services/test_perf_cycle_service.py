"""考核周期服务单元测试

覆盖：状态机单向推进（合法四跃迁/非法跃迁 409/draft 编辑删除限制）、目标整批
提交权重合计 100 校验（不足/超额/非正权重/编码冲突/整批替换）、单目标编辑复核
合计、进度更新 completed 置位与状态门控、评级分布聚合、tenant_id 显式传递。
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError
from framework.tenant.context import TenantContext

from hr.models import Employee, PerfCycle, PerfGoal, PerfReview
from hr.services.perf_cycle_service import perf_cycle_service


def _patch_finalize(count: int = 0):
    """patch 评估服务单例（close 收口写系数挂钩）"""
    patcher = patch("hr.services.perf_review_service.perf_review_service")
    mock_service = patcher.start()
    mock_service.finalize_cycle = AsyncMock(return_value=count)
    return patcher, mock_service


def _patch_perf_setting(values: dict | None = None):
    """patch iam_client 读绩效设置（distribution 规则线/收口系数映射）"""
    client = MagicMock()
    client.get_system_setting = AsyncMock(return_value=values)
    return patch("framework.clients.iam_client.get_iam_client", return_value=client)


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalar_one(self):
        return self._rows[0] if self._rows else 0

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


def _mock_session(get_map=None, execute_results=None) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.flush = AsyncMock()
    added: list = []
    session.add = MagicMock(side_effect=added.append)
    session._added = added
    deleted: list = []
    session.delete = AsyncMock(side_effect=deleted.append)
    session._deleted = deleted
    session.get = AsyncMock(
        side_effect=lambda model, pk: (get_map or {}).get((model.__name__, str(pk)))
    )
    session.execute = AsyncMock(
        side_effect=list(execute_results) if execute_results else []
    )
    return session


def _cycle(**overrides) -> PerfCycle:
    defaults = dict(
        id="cyc-1", tenant_id="t-1", name="2026-H1",
        start_date=date(2026, 1, 1), end_date=date(2026, 6, 30), status="draft",
    )
    defaults.update(overrides)
    return PerfCycle(**defaults)


def _goal(**overrides) -> PerfGoal:
    defaults = dict(
        id="goal-1", tenant_id="t-1", cycle_id="cyc-1", employee_id="emp-1",
        code="G1", name="目标一", weight=Decimal("40"), progress=0, status="open",
    )
    defaults.update(overrides)
    return PerfGoal(**defaults)


def _employee(**overrides) -> Employee:
    defaults = dict(
        id="emp-1", tenant_id="t-1", employee_no="EMP0001",
        name="张三", status="regular",
    )
    defaults.update(overrides)
    return Employee(**defaults)


@pytest.fixture(autouse=True)
def _tenant_context():
    TenantContext.set_tenant_id("t-1")
    yield
    TenantContext.clear()


class TestCycleCrud:
    """周期创建/编辑/删除（draft 限制）"""

    @pytest.mark.asyncio
    async def test_create_cycle_sets_tenant_and_draft(self):
        session = _mock_session(execute_results=[_FakeResult()])
        cycle = await perf_cycle_service.create_cycle(
            session, name="2026-H1", start_date=date(2026, 1, 1), end_date=date(2026, 6, 30)
        )
        assert cycle.tenant_id == "t-1"
        assert cycle.status == "draft"
        assert cycle in session._added

    @pytest.mark.asyncio
    async def test_create_cycle_duplicate_name_rejected(self):
        session = _mock_session(execute_results=[_FakeResult([_cycle()])])
        with pytest.raises(ConflictError, match="已存在"):
            await perf_cycle_service.create_cycle(
                session, name="2026-H1", start_date=date(2026, 1, 1), end_date=date(2026, 6, 30)
            )

    @pytest.mark.asyncio
    async def test_create_cycle_bad_dates_rejected(self):
        session = _mock_session()
        with pytest.raises(BadRequestError, match="截止日期"):
            await perf_cycle_service.create_cycle(
                session, name="X", start_date=date(2026, 6, 30), end_date=date(2026, 1, 1)
            )

    @pytest.mark.asyncio
    async def test_update_cycle_non_draft_rejected(self):
        session = _mock_session(get_map={("PerfCycle", "cyc-1"): _cycle(status="active")})
        with pytest.raises(ConflictError, match="仅草稿"):
            await perf_cycle_service.update_cycle(session, "cyc-1", name="改名")

    @pytest.mark.asyncio
    async def test_delete_cycle_non_draft_rejected(self):
        session = _mock_session(get_map={("PerfCycle", "cyc-1"): _cycle(status="closed")})
        with pytest.raises(ConflictError, match="仅草稿"):
            await perf_cycle_service.delete_cycle(session, "cyc-1")

    @pytest.mark.asyncio
    async def test_get_cycle_not_found(self):
        session = _mock_session()
        with pytest.raises(NotFoundError, match="不存在"):
            await perf_cycle_service.get_cycle(session, "missing")


class TestStateMachine:
    """状态机单向推进"""

    @pytest.mark.asyncio
    async def test_legal_transitions(self):
        for action, source, target in [
            ("activate", "draft", "active"),
            ("scoring", "active", "scoring"),
            ("calibrating", "scoring", "calibrating"),
            ("close", "calibrating", "closed"),
        ]:
            session = _mock_session(
                get_map={("PerfCycle", "cyc-1"): _cycle(status=source)}
            )
            patcher, _ = _patch_finalize()
            try:
                cycle = await perf_cycle_service.transition(session, "cyc-1", action=action)
            finally:
                patcher.stop()
            assert cycle.status == target

    @pytest.mark.asyncio
    async def test_close_triggers_finalize(self):
        session = _mock_session(
            get_map={("PerfCycle", "cyc-1"): _cycle(status="calibrating")}
        )
        patcher, review_service = _patch_finalize(count=3)
        try:
            cycle = await perf_cycle_service.transition(session, "cyc-1", action="close")
        finally:
            patcher.stop()
        review_service.finalize_cycle.assert_awaited_once_with(session, "cyc-1")
        assert cycle.status == "closed"

    @pytest.mark.asyncio
    async def test_illegal_transition_rejected(self):
        session = _mock_session(get_map={("PerfCycle", "cyc-1"): _cycle(status="draft")})
        with pytest.raises(ConflictError, match="仅 active 状态可执行"):
            await perf_cycle_service.transition(session, "cyc-1", action="scoring")

    @pytest.mark.asyncio
    async def test_terminal_state_locked(self):
        session = _mock_session(get_map={("PerfCycle", "cyc-1"): _cycle(status="closed")})
        with pytest.raises(ConflictError, match="仅 draft 状态可执行"):
            await perf_cycle_service.transition(session, "cyc-1", action="activate")

    @pytest.mark.asyncio
    async def test_unknown_action_rejected(self):
        session = _mock_session()
        with pytest.raises(BadRequestError, match="未知状态动作"):
            await perf_cycle_service.transition(session, "cyc-1", action="revert")


class TestSubmitGoals:
    """目标整批提交（权重合计 100）"""

    @pytest.mark.asyncio
    async def test_weight_total_under_100_rejected(self):
        session = _mock_session(
            get_map={("PerfCycle", "cyc-1"): _cycle(status="active"),
                     ("Employee", "emp-1"): _employee()},
            execute_results=[_FakeResult()],
        )
        with pytest.raises(BadRequestError, match="不足 100"):
            await perf_cycle_service.submit_goals(
                session, cycle_id="cyc-1", employee_id="emp-1",
                goals=[{"code": "G1", "name": "目标一", "weight": 40},
                       {"code": "G2", "name": "目标二", "weight": 35}],
            )

    @pytest.mark.asyncio
    async def test_weight_total_over_100_rejected(self):
        session = _mock_session(
            get_map={("PerfCycle", "cyc-1"): _cycle(status="active"),
                     ("Employee", "emp-1"): _employee()},
            execute_results=[_FakeResult()],
        )
        with pytest.raises(BadRequestError, match="超出 100"):
            await perf_cycle_service.submit_goals(
                session, cycle_id="cyc-1", employee_id="emp-1",
                goals=[{"code": "G1", "name": "目标一", "weight": 60},
                       {"code": "G2", "name": "目标二", "weight": 50}],
            )

    @pytest.mark.asyncio
    async def test_submit_goals_sets_tenant_and_replaces_open(self):
        old_goal = _goal(id="goal-old", code="G0")
        session = _mock_session(
            get_map={("PerfCycle", "cyc-1"): _cycle(status="active"),
                     ("Employee", "emp-1"): _employee()},
            execute_results=[_FakeResult(), _FakeResult([old_goal])],
        )
        goals = await perf_cycle_service.submit_goals(
            session, cycle_id="cyc-1", employee_id="emp-1",
            goals=[{"code": "G1", "name": "目标一", "weight": 40},
                   {"code": "G2", "name": "目标二", "weight": 35},
                   {"code": "G3", "name": "目标三", "weight": 25}],
        )
        assert len(goals) == 3
        assert all(goal.tenant_id == "t-1" for goal in goals)
        assert session._deleted == [old_goal]
        assert len(session._added) == 3

    @pytest.mark.asyncio
    async def test_non_positive_weight_rejected(self):
        session = _mock_session(
            get_map={("PerfCycle", "cyc-1"): _cycle(status="active"),
                     ("Employee", "emp-1"): _employee()},
        )
        with pytest.raises(BadRequestError, match="大于 0"):
            await perf_cycle_service.submit_goals(
                session, cycle_id="cyc-1", employee_id="emp-1",
                goals=[{"code": "G1", "name": "目标一", "weight": 0},
                       {"code": "G2", "name": "目标二", "weight": 100}],
            )

    @pytest.mark.asyncio
    async def test_empty_goals_rejected(self):
        session = _mock_session(
            get_map={("PerfCycle", "cyc-1"): _cycle(status="active")},
        )
        with pytest.raises(BadRequestError, match="不可为空"):
            await perf_cycle_service.submit_goals(
                session, cycle_id="cyc-1", employee_id="emp-1", goals=[]
            )

    @pytest.mark.asyncio
    async def test_non_active_cycle_rejected(self):
        session = _mock_session(
            get_map={("PerfCycle", "cyc-1"): _cycle(status="scoring")},
        )
        with pytest.raises(ConflictError, match="进行中"):
            await perf_cycle_service.submit_goals(
                session, cycle_id="cyc-1", employee_id="emp-1",
                goals=[{"code": "G1", "name": "目标一", "weight": 100}],
            )

    @pytest.mark.asyncio
    async def test_duplicate_code_rejected(self):
        session = _mock_session(
            get_map={("PerfCycle", "cyc-1"): _cycle(status="active"),
                     ("Employee", "emp-1"): _employee()},
            execute_results=[_FakeResult([_goal(id="other", code="G1")])],
        )
        with pytest.raises(BadRequestError, match="G1"):
            await perf_cycle_service.submit_goals(
                session, cycle_id="cyc-1", employee_id="emp-1",
                goals=[{"code": "G1", "name": "目标一", "weight": 100}],
            )

    @pytest.mark.asyncio
    async def test_offboarded_employee_rejected(self):
        session = _mock_session(
            get_map={("PerfCycle", "cyc-1"): _cycle(status="active"),
                     ("Employee", "emp-1"): _employee(status="offboarded")},
        )
        with pytest.raises(ConflictError, match="在职"):
            await perf_cycle_service.submit_goals(
                session, cycle_id="cyc-1", employee_id="emp-1",
                goals=[{"code": "G1", "name": "目标一", "weight": 100}],
            )


class TestGoalUpdate:
    """单目标编辑（active 态未完成 + 合计复核）"""

    @pytest.mark.asyncio
    async def test_weight_change_breaking_total_rejected(self):
        goal = _goal(weight=Decimal("40"))
        session = _mock_session(
            get_map={("PerfGoal", "goal-1"): goal,
                     ("PerfCycle", "cyc-1"): _cycle(status="active")},
            execute_results=[_FakeResult([60])],
        )
        with pytest.raises(BadRequestError, match="超出 100"):
            await perf_cycle_service.update_goal(session, "goal-1", weight=Decimal("50"))

    @pytest.mark.asyncio
    async def test_weight_change_within_total_ok(self):
        goal = _goal(weight=Decimal("40"))
        session = _mock_session(
            get_map={("PerfGoal", "goal-1"): goal,
                     ("PerfCycle", "cyc-1"): _cycle(status="active")},
            execute_results=[_FakeResult([60])],
        )
        updated = await perf_cycle_service.update_goal(
            session, "goal-1", weight=Decimal("40"), name="新名称"
        )
        assert updated.name == "新名称"
        assert Decimal(str(updated.weight)) == Decimal("40")

    @pytest.mark.asyncio
    async def test_completed_goal_not_editable(self):
        goal = _goal(status="completed")
        session = _mock_session(
            get_map={("PerfGoal", "goal-1"): goal,
                     ("PerfCycle", "cyc-1"): _cycle(status="active")},
        )
        with pytest.raises(ConflictError, match="已完成"):
            await perf_cycle_service.update_goal(session, "goal-1", name="改名")

    @pytest.mark.asyncio
    async def test_edit_in_scoring_cycle_rejected(self):
        goal = _goal()
        session = _mock_session(
            get_map={("PerfGoal", "goal-1"): goal,
                     ("PerfCycle", "cyc-1"): _cycle(status="scoring")},
        )
        with pytest.raises(ConflictError, match="进行中"):
            await perf_cycle_service.update_goal(session, "goal-1", name="改名")


class TestGoalProgress:
    """进度更新（active/scoring 门控 + completed 置位）"""

    @pytest.mark.asyncio
    async def test_progress_100_completes(self):
        goal = _goal()
        session = _mock_session(
            get_map={("PerfGoal", "goal-1"): goal,
                     ("PerfCycle", "cyc-1"): _cycle(status="active")},
        )
        updated = await perf_cycle_service.update_goal_progress(
            session, "goal-1", progress=100, actual_value="达成"
        )
        assert updated.status == "completed"
        assert updated.progress == 100

    @pytest.mark.asyncio
    async def test_progress_out_of_range_rejected(self):
        goal = _goal()
        session = _mock_session(
            get_map={("PerfGoal", "goal-1"): goal,
                     ("PerfCycle", "cyc-1"): _cycle(status="active")},
        )
        with pytest.raises(BadRequestError, match="0-100"):
            await perf_cycle_service.update_goal_progress(session, "goal-1", progress=101)

    @pytest.mark.asyncio
    async def test_progress_allowed_in_scoring(self):
        goal = _goal()
        session = _mock_session(
            get_map={("PerfGoal", "goal-1"): goal,
                     ("PerfCycle", "cyc-1"): _cycle(status="scoring")},
        )
        updated = await perf_cycle_service.update_goal_progress(
            session, "goal-1", progress=80
        )
        assert updated.status == "open"

    @pytest.mark.asyncio
    async def test_progress_rejected_in_calibrating(self):
        goal = _goal()
        session = _mock_session(
            get_map={("PerfGoal", "goal-1"): goal,
                     ("PerfCycle", "cyc-1"): _cycle(status="calibrating")},
        )
        with pytest.raises(ConflictError, match="进行中/评分中"):
            await perf_cycle_service.update_goal_progress(session, "goal-1", progress=50)

    @pytest.mark.asyncio
    async def test_goal_delete_non_open_rejected(self):
        goal = _goal(status="completed")
        session = _mock_session(
            get_map={("PerfGoal", "goal-1"): goal,
                     ("PerfCycle", "cyc-1"): _cycle(status="active")},
        )
        with pytest.raises(ConflictError, match="不可删除"):
            await perf_cycle_service.delete_goal(session, "goal-1")


class TestDistribution:
    """评级分布聚合（calibrated 优先回退口径由 SQL coalesce 承载）"""

    @pytest.mark.asyncio
    async def test_distribution_aggregation(self):
        session = _mock_session(
            get_map={("PerfCycle", "cyc-1"): _cycle(status="calibrating")},
            execute_results=[_FakeResult([("S", 1), ("A", 2)])],
        )
        with _patch_perf_setting(None):
            data = await perf_cycle_service.distribution(session, "cyc-1")
        assert data["total"] == 3
        assert data["ratings"]["S"] == {"count": 1, "percent": 33.3}
        assert data["ratings"]["A"] == {"count": 2, "percent": 66.7}
        assert data["ratings"]["B"] == {"count": 0, "percent": 0.0}
        assert data["rules"] == {"S": 10.0, "A": 20.0}

    @pytest.mark.asyncio
    async def test_distribution_empty(self):
        session = _mock_session(
            get_map={("PerfCycle", "cyc-1"): _cycle(status="active")},
            execute_results=[_FakeResult()],
        )
        with _patch_perf_setting(None):
            data = await perf_cycle_service.distribution(session, "cyc-1")
        assert data["total"] == 0
        assert all(item == {"count": 0, "percent": 0.0} for item in data["ratings"].values())

    @pytest.mark.asyncio
    async def test_distribution_rules_from_setting(self):
        session = _mock_session(
            get_map={("PerfCycle", "cyc-1"): _cycle(status="calibrating")},
            execute_results=[_FakeResult([("S", 2)])],
        )
        with _patch_perf_setting({"distribution_rules": {"S": 5, "A": 25}}):
            data = await perf_cycle_service.distribution(session, "cyc-1")
        assert data["rules"] == {"S": 5.0, "A": 25.0}


class TestListCycles:
    """列表统计（目标数/评估数）"""

    @pytest.mark.asyncio
    async def test_list_cycles_with_stats(self):
        cycles = [_cycle(id="c1"), _cycle(id="c2", name="2025-H2")]
        session = _mock_session(
            execute_results=[
                _FakeResult([2]),
                _FakeResult(cycles),
                _FakeResult([("c1", 5)]),
                _FakeResult([("c1", 3), ("c2", 1)]),
            ],
        )
        result = await perf_cycle_service.list_cycles(session)
        assert result["total"] == 2
        assert result["items"][0]["goal_count"] == 5
        assert result["items"][0]["review_count"] == 3
        assert result["items"][1]["goal_count"] == 0
        assert result["items"][1]["review_count"] == 1
