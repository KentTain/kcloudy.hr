"""考勤服务单元测试

覆盖：状态判定矩阵（双缺/单缺/迟到早退组合）、同键覆盖写入（含 tenant_id
显式传参与工作时长计算）、统计口径（出勤人次/迟到/早退/缺勤/出勤率、部门切片）。
"""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.tenant.context import TenantContext

from hr.models import AttendanceRecord
from hr.services.attendance_service import (
    attendance_service,
    judge_status,
)


class _FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one(self):
        if self._scalar is not None:
            return self._scalar
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


def _mock_session(execute_results=None) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.flush = AsyncMock()
    added: list = []
    session.add = MagicMock(side_effect=added.append)
    session._added = added
    session.execute = AsyncMock(
        side_effect=list(execute_results) if execute_results else []
    )
    return session


def _record(**overrides) -> AttendanceRecord:
    defaults = dict(
        id="rec-1",
        tenant_id="t-1",
        employee_id="emp-1",
        work_date=date(2026, 10, 16),
        status="normal",
        source="excel",
    )
    defaults.update(overrides)
    return AttendanceRecord(**defaults)


@pytest.fixture(autouse=True)
def _tenant_context():
    TenantContext.set_tenant_id("t-1")
    yield
    TenantContext.clear()


class TestJudgeStatus:
    """状态判定（一期固定班次 09:00-18:00）"""

    def test_both_missing_is_absent(self):
        assert judge_status(None, None) == "absent"

    def test_single_missing_is_missing_card(self):
        nine = datetime(2026, 10, 16, 9, 0)
        assert judge_status(nine, None) == "missing_card"
        assert judge_status(None, datetime(2026, 10, 16, 18, 0)) == "missing_card"

    def test_late_and_early_combo(self):
        assert (
            judge_status(
                datetime(2026, 10, 16, 9, 30), datetime(2026, 10, 16, 17, 0)
            )
            == "late_early"
        )

    def test_late_only(self):
        assert (
            judge_status(
                datetime(2026, 10, 16, 9, 1), datetime(2026, 10, 16, 18, 0)
            )
            == "late"
        )

    def test_early_leave_only(self):
        assert (
            judge_status(
                datetime(2026, 10, 16, 9, 0), datetime(2026, 10, 16, 17, 59)
            )
            == "early_leave"
        )

    def test_normal_on_boundary(self):
        assert (
            judge_status(
                datetime(2026, 10, 16, 9, 0), datetime(2026, 10, 16, 18, 0)
            )
            == "normal"
        )


class TestUpsertRecord:
    """同键覆盖写入"""

    @pytest.mark.asyncio
    async def test_overwrite_existing(self):
        existing = _record(status="absent")
        session = _mock_session(execute_results=[_FakeResult(rows=[existing])])
        record, created = await attendance_service.upsert_record(
            session,
            employee_id="emp-1",
            work_date=date(2026, 10, 16),
            status="leave",
            source="leave",
            remark="请假：年假",
        )
        assert created is False
        assert record is existing
        assert record.status == "leave"
        assert record.source == "leave"
        assert not [o for o in session._added if isinstance(o, AttendanceRecord)]

    @pytest.mark.asyncio
    async def test_create_new_with_tenant_and_work_hours(self):
        session = _mock_session(execute_results=[_FakeResult(rows=[])])
        record, created = await attendance_service.upsert_record(
            session,
            employee_id="emp-1",
            work_date=date(2026, 10, 16),
            status="normal",
            source="excel",
            check_in_time=datetime(2026, 10, 16, 9, 0),
            check_out_time=datetime(2026, 10, 16, 18, 30),
        )
        assert created is True
        assert record.tenant_id == "t-1"
        assert record.work_hours == 9.5

    @pytest.mark.asyncio
    async def test_negative_span_ignored_for_work_hours(self):
        session = _mock_session(execute_results=[_FakeResult(rows=[])])
        record, _ = await attendance_service.upsert_record(
            session,
            employee_id="emp-1",
            work_date=date(2026, 10, 16),
            status="missing_card",
            source="excel",
            check_in_time=datetime(2026, 10, 16, 18, 0),
            check_out_time=datetime(2026, 10, 16, 9, 0),
        )
        assert record.work_hours is None


class TestStatsAggregation:
    """统计口径"""

    def test_cards_counts_and_rate(self):
        cards = attendance_service._aggregate_cards(
            {
                "normal": 6,
                "late": 2,
                "late_early": 1,
                "early_leave": 1,
                "missing_card": 2,
                "absent": 3,
                "leave": 5,
            }
        )
        assert cards.total_records == 20
        # 出勤人次 = normal+late+early_leave+late_early+missing_card（缺勤/请假不计）
        assert cards.attendance_count == 12
        assert cards.late_count == 3
        assert cards.early_leave_count == 2
        assert cards.absent_count == 3
        assert cards.attendance_rate == 60.0

    def test_cards_empty_returns_none_rate(self):
        cards = attendance_service._aggregate_cards({})
        assert cards.total_records == 0
        assert cards.attendance_rate is None

    def test_org_stat_slices(self):
        stat = attendance_service._aggregate_org_stat(
            "org-1", {"normal": 8, "late": 2}
        )
        assert stat.org_id == "org-1"
        assert stat.total_records == 10
        assert stat.attendance_count == 10
        assert stat.attendance_rate == 100.0
        assert stat.missing_card_count == 0

    @pytest.mark.asyncio
    async def test_get_stats_groups_and_sorts(self):
        session = _mock_session(
            execute_results=[
                _FakeResult(rows=[("normal", 3), ("absent", 1)]),
                _FakeResult(
                    rows=[
                        ("org-1", "normal", 3),
                        ("org-2", "normal", 1),
                        ("org-2", "absent", 1),
                    ]
                ),
            ]
        )
        stats = await attendance_service.get_stats(session)
        assert stats.cards.total_records == 4
        assert stats.cards.attendance_count == 3
        # 按出勤人次降序
        assert [s.org_id for s in stats.org_slices] == ["org-1", "org-2"]
        assert stats.org_slices[1].absent_count == 1


class TestListRecords:
    """记录列表"""

    @pytest.mark.asyncio
    async def test_paginated_with_join_fields(self):
        employee = MagicMock()
        employee.employee_no = "EMP0001"
        employee.name = "张三"
        employee.org_id = "org-1"
        record = _record()
        session = _mock_session(
            execute_results=[
                _FakeResult(scalar=7),
                _FakeResult(rows=[(record, employee)]),
            ]
        )
        result = await attendance_service.list_records(
            session, status="normal", page=1, page_size=20
        )
        assert result["total"] == 7
        assert result["items"][0].employee_no == "EMP0001"
        assert result["items"][0].employee_name == "张三"
