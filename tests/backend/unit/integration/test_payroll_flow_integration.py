"""发薪批次流集成测试（§8.3）：定薪 → 调薪 → 试算（多段分段折算）→ 确认 → 发放。

真库直跑（hr schema），事务内断言不 commit（回滚零清理）；
试算任务化为外皮，此处直调 calculate_run（handler 内核同函数）。
"""

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from framework.common.ctx import set_user
from framework.common.exceptions import BadRequestError, ConflictError
from framework.tenant.context import TenantContext
from hr.models import Employee, EmployeeSalaryPackage, PayrollEntry, SalaryItem
from hr.schemas.salary import SalaryPackageCreate, SalaryPackageItemCreate
from hr.services.payroll_service import payroll_service
from hr.services.salary_package_service import salary_package_service

pytestmark = pytest.mark.integration

TENANT = "itest-hr-payroll"


@pytest_asyncio.fixture()
async def session(postgres_engine) -> AsyncIterator[AsyncSession]:
    from framework.database.events.tenant import register_tenant_events
    from framework.database.interceptors.query import register_tenant_auto_filter
    from framework.tasks.store_protocol import register_task_store_provider
    from iam.services.task_store_provider import iam_task_store_provider

    register_task_store_provider(iam_task_store_provider)

    register_tenant_auto_filter()
    register_tenant_events()
    TenantContext.set_tenant_id(TENANT)
    # 定薪流水 operator_id 非空约束需要用户上下文
    set_user(user_id="itest-operator", tenant_id=TENANT)
    maker = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with maker() as sess:
        sess.add(
            Employee(
                tenant_id=TENANT,
                employee_no="ITEST-P-001",
                name="薪酬探针员工",
                status="regular",
                hire_date=date.today() - timedelta(days=400),
            )
        )
        sess.add(
            SalaryItem(
                tenant_id=TENANT,
                code="itest_base",
                name="基本工资（探针）",
                category="base",
                ext_data={"monthly_fixed": True},
                can_edit=True,
            )
        )
        await sess.flush()
        yield sess
        await sess.rollback()
    TenantContext.clear()


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@pytest.mark.asyncio
async def test_full_payroll_flow_with_segmented_proration(session: AsyncSession):
    """月内两次定薪 → 试算生成两段折算明细 → 确认回写总额 → 发放；状态机拦截"""
    employee = (
        await session.execute(select(Employee).where(Employee.employee_no == "ITEST-P-001"))
    ).scalars().one()
    item = (
        await session.execute(select(SalaryItem).where(SalaryItem.code == "itest_base"))
    ).scalars().one()

    # 选下个月做发薪期间：两次定薪生效日（10 日 / 20 日）恒满足「不早于当日」
    base = date.today().replace(day=1) + timedelta(days=32)
    month_start = base.replace(day=1)
    effective_1 = month_start + timedelta(days=9)
    effective_2 = month_start + timedelta(days=19)
    period = f"{month_start.year}-{month_start.month:02d}"

    await salary_package_service.adjust(
        session,
        str(employee.id),
        SalaryPackageCreate(
            items=[SalaryPackageItemCreate(item_id=str(item.id), amount=3100)],
            reason="hire",
            effective_from=effective_1,
        ),
    )
    # 同项二次调薪：闭合旧区间，形成当月两段
    created = await salary_package_service.adjust(
        session,
        str(employee.id),
        SalaryPackageCreate(
            items=[SalaryPackageItemCreate(item_id=str(item.id), amount=5000)],
            reason="adjust",
            effective_from=effective_2,
        ),
    )
    assert len(created) == 1

    packages = (
        await session.execute(select(EmployeeSalaryPackage).order_by(EmployeeSalaryPackage.effective_from))
    ).scalars().all()
    assert len(packages) == 2
    assert packages[0].effective_to == effective_2 - timedelta(days=1)
    assert packages[1].effective_to is None

    run_payload = await payroll_service.create_run(session, period)
    run = run_payload["run"]
    assert run_payload["task_id"]

    await payroll_service.calculate_run(session, str(run.id))

    entries = (
        await session.execute(select(PayrollEntry))
    ).scalars().all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.item_code == "itest_base"

    # 分段折算期望：段1=10日~19日按 3100，段2=20日~月末按 5000，日金额=月金额/当月天数
    days_in_month = calendar.monthrange(month_start.year, month_start.month)[1]
    seg1_days = (effective_2 - timedelta(days=1) - effective_1).days + 1
    seg2_days = days_in_month - effective_2.day + 1
    amt1 = _q2(Decimal("3100") * seg1_days / Decimal(days_in_month))
    amt2 = _q2(Decimal("5000") * seg2_days / Decimal(days_in_month))
    assert _q2(Decimal(str(entry.amount))) == _q2(amt1 + amt2)
    assert entry.note is not None and "分段折算" in entry.note

    with pytest.raises(ConflictError, match="已存在"):
        await payroll_service.create_run(session, period)

    confirmed = await payroll_service.confirm_run(session, str(run.id))
    assert confirmed.status == "confirmed"
    assert confirmed.employee_count == 1
    assert _q2(Decimal(str(confirmed.total_amount))) == _q2(amt1 + amt2)

    paid = await payroll_service.pay_run(session, str(run.id))
    assert paid.status == "paid"
    assert paid.pay_date == date.today()

    with pytest.raises(ConflictError, match="不可取消"):
        await payroll_service.cancel_run(session, str(run.id))


@pytest.mark.asyncio
async def test_adjust_rejects_backdated_and_offboarded(session: AsyncSession):
    """生效日早于当日 / 非在职状态不可发起定薪"""
    employee = (
        await session.execute(select(Employee).where(Employee.employee_no == "ITEST-P-001"))
    ).scalars().one()
    item = (
        await session.execute(select(SalaryItem).where(SalaryItem.code == "itest_base"))
    ).scalars().one()

    with pytest.raises(BadRequestError, match="不可早于当日"):
        await salary_package_service.adjust(
            session,
            str(employee.id),
            SalaryPackageCreate(
                items=[SalaryPackageItemCreate(item_id=str(item.id), amount=3000)],
                reason="adjust",
                effective_from=date.today() - timedelta(days=1),
            ),
        )

    employee.status = "offboarded"
    with pytest.raises(ConflictError, match="不可发起"):
        await salary_package_service.adjust(
            session,
            str(employee.id),
            SalaryPackageCreate(
                items=[SalaryPackageItemCreate(item_id=str(item.id), amount=3000)],
                reason="adjust",
                effective_from=date.today(),
            ),
        )
