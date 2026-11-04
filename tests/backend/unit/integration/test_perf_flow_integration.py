"""绩效全流程集成测试（二期 F.1）：建周期 → 激活 → 目标整批提交 → 评分中发起
评估 → 评分 → 校准中校准 → 收口写系数 → 发薪试算消费系数。

真库直跑（hr schema），事务内断言不 commit（回滚零清理）；
绩效设置读 iam SystemSetting（探针租户无配置回退内置映射 S=1.5/A=1.2）。
"""

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
from hr.models import Employee, PayrollEntry, PerfCycle, PerfGoal, PerfReview, SalaryItem
from hr.schemas.salary import SalaryPackageCreate, SalaryPackageItemCreate
from hr.services.payroll_service import payroll_service
from hr.services.perf_cycle_service import perf_cycle_service
from hr.services.perf_review_service import perf_review_service
from hr.services.salary_package_service import salary_package_service

pytestmark = pytest.mark.integration

TENANT = "itest-hr-perf"


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
    set_user(user_id="itest-operator", tenant_id=TENANT)
    maker = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with maker() as sess:
        employee = Employee(
            tenant_id=TENANT,
            employee_no="ITEST-PR-001",
            name="绩效探针员工",
            status="regular",
            hire_date=date.today() - timedelta(days=400),
        )
        sess.add(employee)
        item = SalaryItem(
            tenant_id=TENANT,
            code="itest_perf_bonus",
            name="绩效工资（探针）",
            category="performance",
            ext_data={"monthly_fixed": True},
            can_edit=True,
        )
        sess.add(item)
        await sess.flush()
        yield sess
        await sess.rollback()
    TenantContext.clear()


def _q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@pytest.mark.asyncio
async def test_full_perf_flow_to_payroll_consumption(session: AsyncSession):
    """五态状态机全推进 + 系数收口 + 发薪试算放大绩效项"""
    employee = (
        await session.execute(select(Employee).where(Employee.employee_no == "ITEST-PR-001"))
    ).scalars().one()
    item = (
        await session.execute(select(SalaryItem).where(SalaryItem.code == "itest_perf_bonus"))
    ).scalars().one()

    # ── 周期：draft → active → scoring → calibrating → closed ──
    cycle = await perf_cycle_service.create_cycle(
        session,
        name="ITEST 绩效周期",
        start_date=date.today() - timedelta(days=180),
        end_date=date.today() - timedelta(days=1),
    )
    assert cycle.status == "draft"

    with pytest.raises(ConflictError, match="仅"):
        await perf_cycle_service.submit_goals(
            session, cycle_id=str(cycle.id), employee_id=str(employee.id), goals=[]
        )

    await perf_cycle_service.transition(session, str(cycle.id), action="activate")

    with pytest.raises(BadRequestError, match="权重"):
        await perf_cycle_service.submit_goals(
            session,
            cycle_id=str(cycle.id),
            employee_id=str(employee.id),
            goals=[{"code": "ITEST-G-001", "name": "交付达成", "weight": 60}],
        )

    goals = await perf_cycle_service.submit_goals(
        session,
        cycle_id=str(cycle.id),
        employee_id=str(employee.id),
        goals=[
            {"code": "ITEST-G-001", "name": "交付达成", "weight": 60, "target_value": "10"},
            {"code": "ITEST-G-002", "name": "质量达标", "weight": 40},
        ],
    )
    assert len(goals) == 2
    assert all(goal.status == "open" for goal in goals)

    await perf_cycle_service.transition(session, str(cycle.id), action="scoring")

    # ── 评估：发起 → 评分 ──
    created = await perf_review_service.create_reviews(
        session,
        cycle_id=str(cycle.id),
        items=[{"employee_id": str(employee.id), "reviewer_employee_id": str(employee.id)}],
    )
    assert created["created"] == 1
    review = (
        await session.execute(
            select(PerfReview).where(PerfReview.cycle_id == str(cycle.id))
        )
    ).scalars().one()
    assert review.status == "pending"

    await perf_review_service.submit_score(
        session, str(review.id), score=Decimal("88"), rating="A", self_score=Decimal("85")
    )
    assert review.status == "submitted"
    assert review.rating == "A"

    # 校准中态评分被拒（周期状态门控）
    await perf_cycle_service.transition(session, str(cycle.id), action="calibrating")
    with pytest.raises(ConflictError, match="评分中"):
        await perf_review_service.submit_score(
            session, str(review.id), score=Decimal("90"), rating="S"
        )

    calibrated = await perf_review_service.calibrate(
        session, str(review.id), rating="S", comment="超额达成校准为 S", operator_user_id="itest-operator"
    )
    assert calibrated.status == "calibrated"
    assert calibrated.calibrated_rating == "S"
    assert calibrated.calibrated_by_user_id == "itest-operator"

    # ── 收口：close 挂 finalize 写系数（校准评级 S → 内置映射 1.5） ──
    await perf_cycle_service.transition(session, str(cycle.id), action="close")
    assert cycle.status == "closed"
    assert review.coefficient == Decimal("1.5")

    distribution = await perf_cycle_service.distribution(session, str(cycle.id))
    assert distribution["total"] == 1
    assert distribution["ratings"]["S"]["count"] == 1

    # ── 发薪联动：绩效项金额 = 定薪 × 系数 ──
    next_month = (date.today().replace(day=1) + timedelta(days=32)).replace(day=1)
    period = f"{next_month.year}-{next_month.month:02d}"
    await salary_package_service.adjust(
        session,
        str(employee.id),
        SalaryPackageCreate(
            items=[SalaryPackageItemCreate(item_id=str(item.id), amount=1000)],
            reason="hire",
            effective_from=next_month,
        ),
    )

    run_payload = await payroll_service.create_run(session, period)
    await payroll_service.calculate_run(session, str(run_payload["run"].id))

    entry = (
        await session.execute(select(PayrollEntry).where(PayrollEntry.item_code == "itest_perf_bonus"))
    ).scalars().one()
    assert _q2(Decimal(str(entry.amount))) == _q2(Decimal("1000") * Decimal("1.5"))

    with pytest.raises(ConflictError, match="已存在"):
        await payroll_service.create_run(session, period)


@pytest.mark.asyncio
async def test_goal_weight_must_sum_to_full(session: AsyncSession):
    """权重超额同样拒绝（合计须恰好 100）"""
    employee = (
        await session.execute(select(Employee).where(Employee.employee_no == "ITEST-PR-001"))
    ).scalars().one()
    cycle = await perf_cycle_service.create_cycle(
        session,
        name="ITEST 权重探针周期",
        start_date=date.today() - timedelta(days=30),
        end_date=date.today() + timedelta(days=30),
    )
    await perf_cycle_service.transition(session, str(cycle.id), action="activate")
    with pytest.raises(BadRequestError, match="权重"):
        await perf_cycle_service.submit_goals(
            session,
            cycle_id=str(cycle.id),
            employee_id=str(employee.id),
            goals=[
                {"code": "ITEST-G-101", "name": "目标一", "weight": 60},
                {"code": "ITEST-G-102", "name": "目标二", "weight": 50},
            ],
        )


@pytest.mark.asyncio
async def test_illegal_transition_rejected(session: AsyncSession):
    """draft 态不可直接进入评分中（状态机单向）"""
    cycle = await perf_cycle_service.create_cycle(
        session,
        name="ITEST 状态机探针周期",
        start_date=date.today(),
        end_date=date.today() + timedelta(days=90),
    )
    with pytest.raises(ConflictError, match="仅 active"):
        await perf_cycle_service.transition(session, str(cycle.id), action="scoring")
