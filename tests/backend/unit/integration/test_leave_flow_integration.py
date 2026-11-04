"""假勤审批流集成测试（§8.4）：建类型 → 提交（冻结）→ 拦截（余额不足/重叠/
驳回空意见）→ 驳回释放 → 重提 → 审批（冻结转已用 + 逐日考勤回写）。

真库直跑（hr schema），事务内断言不 commit（回滚零清理）。
"""

from datetime import date, datetime, timedelta
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from framework.common.exceptions import BadRequestError, ConflictError
from framework.tenant.context import TenantContext
from hr.models import AttendanceRecord, Employee, LeaveBalance, LeaveType
from hr.schemas.leave import LeaveRequestCreate, LeaveTypeCreate
from hr.services.leave_request_service import leave_request_service
from hr.services.leave_service import leave_service

pytestmark = pytest.mark.integration

TENANT = "itest-hr-leave"


@pytest_asyncio.fixture()
async def session(postgres_engine) -> AsyncIterator[AsyncSession]:
    from framework.database.events.tenant import register_tenant_events
    from framework.database.interceptors.query import register_tenant_auto_filter

    register_tenant_auto_filter()
    register_tenant_events()
    TenantContext.set_tenant_id(TENANT)
    maker = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with maker() as sess:
        sess.add(
            Employee(
                tenant_id=TENANT,
                employee_no="ITEST-L-001",
                name="假勤探针员工",
                status="regular",
                hire_date=date.today() - timedelta(days=300),
            )
        )
        await sess.flush()
        yield sess
        await sess.rollback()
    TenantContext.clear()


async def _balance(session: AsyncSession, employee_id: str, leave_type: LeaveType, year: int) -> LeaveBalance:
    return await leave_service.get_or_create_balance(session, employee_id, leave_type, year)


@pytest.mark.asyncio
async def test_leave_submit_reject_approve_flow(session: AsyncSession):
    """提交冻结 → 拦截（余额不足/重叠/驳回空意见）→ 驳回释放 → 重提 → 审批联动"""
    employee = (
        await session.execute(select(Employee).where(Employee.employee_no == "ITEST-L-001"))
    ).scalars().one()
    employee_id = str(employee.id)

    leave_type = await leave_service.create_type(
        session,
        LeaveTypeCreate(
            code="itest_annual",
            name="年假（探针）",
            unit="day",
            paid=True,
            quota_rule="annual_fixed",
            default_quota=5,
        ),
    )
    year = date.today().year

    # 提交 2 天：余额惰性建行 + 冻结 2
    start = datetime.combine(date.today() + timedelta(days=1), datetime.min.time()).replace(hour=9)
    end = datetime.combine(date.today() + timedelta(days=2), datetime.min.time()).replace(hour=18)
    request = await leave_request_service.submit_request(
        session,
        employee_id,
        LeaveRequestCreate(leave_type_id=str(leave_type.id), start_time=start, end_time=end, reason="家事"),
    )
    assert request.status == "pending"
    assert request.duration == 2.0

    balance = await _balance(session, employee_id, leave_type, year)
    assert float(balance.total_quota) == 5.0
    assert float(balance.frozen) == 2.0
    assert float(balance.used) == 0.0

    # 余额不足：再提 4 天（错开区间不触发重叠）→ 可用仅 3
    with pytest.raises(BadRequestError, match="假期余额不足"):
        await leave_request_service.submit_request(
            session,
            employee_id,
            LeaveRequestCreate(
                leave_type_id=str(leave_type.id),
                start_time=start + timedelta(days=10),
                end_time=end + timedelta(days=13),
                reason="长途",
            ),
        )

    # 区间重叠：与待审批单相交
    with pytest.raises(ConflictError, match="重叠"):
        await leave_request_service.submit_request(
            session,
            employee_id,
            LeaveRequestCreate(
                leave_type_id=str(leave_type.id),
                start_time=start,
                end_time=end + timedelta(days=2),
                reason="重叠探针",
            ),
        )

    # 驳回意见必填；驳回后冻结释放
    with pytest.raises(BadRequestError, match="驳回须填写审批意见"):
        await leave_request_service.reject(session, str(request.id), approver_id="itest-approver", comment="  ")
    rejected = await leave_request_service.reject(
        session, str(request.id), approver_id="itest-approver", comment="事由不足"
    )
    assert rejected.status == "rejected"
    await session.flush()
    await session.refresh(balance)
    assert float(balance.frozen) == 0.0

    # 重提（原单已驳回不再重叠）→ 审批通过：冻结转已用 + 逐日考勤回写
    resubmitted = await leave_request_service.submit_request(
        session,
        employee_id,
        LeaveRequestCreate(leave_type_id=str(leave_type.id), start_time=start, end_time=end, reason="家事（补充）"),
    )
    approved = await leave_request_service.approve(
        session, str(resubmitted.id), approver_id="itest-approver", comment="同意"
    )
    assert approved.status == "approved"
    assert approved.approver_id == "itest-approver"

    await session.refresh(balance)
    assert float(balance.frozen) == 0.0
    assert float(balance.used) == 2.0

    records = (
        await session.execute(
            select(AttendanceRecord).order_by(AttendanceRecord.work_date)
        )
    ).scalars().all()
    assert [r.work_date for r in records] == [start.date(), end.date()]
    assert all(r.status == "leave" and r.source == "leave" for r in records)
    assert all("年假" in (r.remark or "") for r in records)


@pytest.mark.asyncio
async def test_cancel_pending_request_releases_frozen(session: AsyncSession):
    """本人撤销待审批单：状态 cancelled + 冻结释放；非本人撤销被拒"""
    employee = (
        await session.execute(select(Employee).where(Employee.employee_no == "ITEST-L-001"))
    ).scalars().one()
    employee_id = str(employee.id)

    leave_type = await leave_service.create_type(
        session,
        LeaveTypeCreate(
            code="itest_personal",
            name="事假（探针）",
            unit="day",
            paid=False,
            quota_rule="annual_fixed",
            default_quota=3,
        ),
    )
    start = datetime.combine(date.today() + timedelta(days=5), datetime.min.time()).replace(hour=9)
    end = datetime.combine(date.today() + timedelta(days=5), datetime.min.time()).replace(hour=18)
    request = await leave_request_service.submit_request(
        session,
        employee_id,
        LeaveRequestCreate(leave_type_id=str(leave_type.id), start_time=start, end_time=end, reason="办事"),
    )
    balance = await _balance(session, employee_id, leave_type, date.today().year)
    assert float(balance.frozen) == 1.0

    with pytest.raises(ConflictError, match="仅可撤销本人"):
        await leave_request_service.cancel_request(session, str(request.id), "someone-else")

    cancelled = await leave_request_service.cancel_request(session, str(request.id), employee_id)
    assert cancelled.status == "cancelled"
    await session.flush()
    await session.refresh(balance)
    assert float(balance.frozen) == 0.0
