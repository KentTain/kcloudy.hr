"""异动服务单元测试

覆盖：状态机（probate 仅试用期/离职拒绝重复）、生效日期校验、
调岗/职级变更入参校验、离职事件发布（事务内）。
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ConflictError

from hr.models import Employee, EmployeeChange
from hr.schemas.change import ChangeCreate
from hr.services.change_service import ChangeService


def _change_stub(change_type: str, effective_date) -> AsyncMock:
    """record_change 桩：返回已填充主键的流水（模拟 flush 后的列默认值）。"""
    return AsyncMock(
        return_value=EmployeeChange(
            id="c-1",
            employee_id="e-1",
            change_type=change_type,
            before_data=None,
            after_data={},
            effective_date=effective_date,
            operator_id=None,
        )
    )


def _mock_session(get_result=None) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=get_result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


def _employee(**overrides) -> Employee:
    defaults = dict(
        id="e-1",
        tenant_id="t-1",
        employee_no="EMP000001",
        name="张三",
        status="probation",
        org_id="org-1",
        hire_date=date(2025, 1, 1),
    )
    defaults.update(overrides)
    return Employee(**defaults)


class TestStateMachine:
    """状态机"""

    @pytest.mark.asyncio
    async def test_probate_requires_probation(self):
        session = _mock_session(get_result=_employee(status="regular"))
        data = ChangeCreate(employee_id="e-1", change_type="probate", effective_date=date.today())
        with pytest.raises(ConflictError):
            await ChangeService().submit_change(session, "e-1", data)

    @pytest.mark.asyncio
    async def test_probate_success(self):
        employee = _employee(status="probation")
        session = _mock_session(get_result=employee)
        data = ChangeCreate(employee_id="e-1", change_type="probate", effective_date=date.today())
        with patch(
            "hr.services.change_service.ChangeService.record_change",
            new=_change_stub("probate", data.effective_date),
        ) as rc:
            await ChangeService().submit_change(session, "e-1", data)
        assert employee.status == "regular"
        assert employee.regular_date == date.today()
        rc.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_offboard_rejects_repeat(self):
        session = _mock_session(get_result=_employee(status="offboarded"))
        data = ChangeCreate(employee_id="e-1", change_type="offboard", effective_date=date.today())
        with pytest.raises(ConflictError, match="不允许发起"):
            await ChangeService().submit_change(session, "e-1", data)

    @pytest.mark.asyncio
    async def test_past_effective_date_rejected(self):
        session = _mock_session(get_result=_employee())
        data = ChangeCreate(
            employee_id="e-1",
            change_type="transfer",
            effective_date=date.today() - timedelta(days=1),
        )
        with pytest.raises(BadRequestError, match="生效日期"):
            await ChangeService().submit_change(session, "e-1", data)

    @pytest.mark.asyncio
    async def test_transfer_requires_target(self):
        session = _mock_session(get_result=_employee())
        data = ChangeCreate(employee_id="e-1", change_type="transfer", effective_date=date.today())
        with pytest.raises(BadRequestError, match="调岗"):
            await ChangeService().submit_change(session, "e-1", data)

    @pytest.mark.asyncio
    async def test_level_change_requires_job_level(self):
        session = _mock_session(get_result=_employee(status="regular"))
        data = ChangeCreate(employee_id="e-1", change_type="level_change", effective_date=date.today())
        with pytest.raises(BadRequestError, match="职级"):
            await ChangeService().submit_change(session, "e-1", data)

    @pytest.mark.asyncio
    async def test_level_change_success(self):
        employee = _employee(status="regular", job_level="P5")
        session = _mock_session(get_result=employee)
        data = ChangeCreate(
            employee_id="e-1", change_type="level_change", effective_date=date.today(), job_level="P6"
        )
        with patch(
            "hr.services.change_service.ChangeService.record_change",
            new=_change_stub("level_change", data.effective_date),
        ):
            await ChangeService().submit_change(session, "e-1", data)
        assert employee.job_level == "P6"


class TestOffboardEvent:
    """离职事件"""

    @pytest.mark.asyncio
    async def test_offboard_publishes_event(self):
        employee = _employee(status="regular", user_id="u-1")
        session = _mock_session(get_result=employee)
        data = ChangeCreate(
            employee_id="e-1", change_type="offboard", effective_date=date.today(), reason="个人原因"
        )
        with (
            patch(
                "hr.services.change_service.ChangeService.record_change",
                new=_change_stub("offboard", data.effective_date),
            ),
            patch("hr.services.change_service.event_publisher.publish", new=AsyncMock()) as publish,
        ):
            await ChangeService().submit_change(session, "e-1", data)
        publish.assert_awaited_once()
        event = publish.await_args.args[0]
        assert event.employee_id == "e-1"
        assert event.user_id == "u-1"

    @pytest.mark.asyncio
    async def test_non_offboard_no_event(self):
        session = _mock_session(get_result=_employee())
        data = ChangeCreate(employee_id="e-1", change_type="probate", effective_date=date.today())
        with (
            patch(
                "hr.services.change_service.ChangeService.record_change",
                new=_change_stub("probate", data.effective_date),
            ),
            patch("hr.services.change_service.event_publisher.publish", new=AsyncMock()) as publish,
        ):
            await ChangeService().submit_change(session, "e-1", data)
        publish.assert_not_awaited()
