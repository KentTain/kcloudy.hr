"""标准代发导出集成测试（§7 批 G.1）：定薪 → 试算 → 确认 → 导出 xlsx 内容校验。

真库直跑（hr schema），事务内断言不 commit（回滚零清理）；
验证状态机拦截（draft 不可导）与导出内容（工号/姓名/密文解密/应发实发）。
"""

import io
from datetime import date, timedelta
from typing import AsyncIterator

import pytest
import pytest_asyncio
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from framework.common.ctx import set_user
from framework.common.exceptions import ConflictError
from framework.tenant.context import TenantContext
from framework.utils.crypto import encrypt
from hr.models import Employee, SalaryItem
from hr.schemas.salary import SalaryPackageCreate, SalaryPackageItemCreate
from hr.services.payroll_service import payroll_service
from hr.services.salary_package_service import salary_package_service

pytestmark = pytest.mark.integration

TENANT = "itest-hr-export"


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
        sess.add(
            Employee(
                tenant_id=TENANT,
                employee_no="ITEST-E-001",
                name="代发探针员工",
                status="regular",
                hire_date=date.today() - timedelta(days=300),
                id_card_enc=encrypt("110101199001010011"),
                bank_card_enc=encrypt("6222020200112233445"),
                bank_name="测试银行",
            )
        )
        sess.add(
            SalaryItem(
                tenant_id=TENANT,
                code="itest_exp_base",
                name="基本工资（导出探针）",
                category="base",
                ext_data={"monthly_fixed": True},
                can_edit=True,
            )
        )
        sess.add(
            SalaryItem(
                tenant_id=TENANT,
                code="itest_exp_ded",
                name="社保扣减（导出探针）",
                category="deduction",
                ext_data={"monthly_fixed": True},
                can_edit=True,
            )
        )
        await sess.flush()
        yield sess
        await sess.rollback()
    TenantContext.clear()


@pytest.mark.asyncio
async def test_export_run_content_and_state_guard(session: AsyncSession):
    """draft 态拒绝导出；确认后导出内容含密文解密明文与应发/实发差额"""
    employee = (
        await session.execute(select(Employee).where(Employee.employee_no == "ITEST-E-001"))
    ).scalars().one()
    items = (
        await session.execute(select(SalaryItem).where(SalaryItem.code.in_(["itest_exp_base", "itest_exp_ded"])))
    ).scalars().all()
    item_by_code = {item.code: item for item in items}

    next_month_first = date.today().replace(day=1) + timedelta(days=32)
    month_start = next_month_first.replace(day=1)
    period = f"{month_start.year}-{month_start.month:02d}"

    await salary_package_service.adjust(
        session,
        str(employee.id),
        SalaryPackageCreate(
            items=[
                SalaryPackageItemCreate(item_id=str(item_by_code["itest_exp_base"].id), amount=5000),
                SalaryPackageItemCreate(item_id=str(item_by_code["itest_exp_ded"].id), amount=500),
            ],
            reason="hire",
            effective_from=month_start,
        ),
    )

    run = (await payroll_service.create_run(session, period))["run"]
    with pytest.raises(ConflictError, match="仅确认/已发放批次可导出"):
        await payroll_service.export_run(session, str(run.id))

    await payroll_service.calculate_run(session, str(run.id))
    await payroll_service.confirm_run(session, str(run.id))

    filename, content = await payroll_service.export_run(session, str(run.id))
    assert filename == f"标准代发-{period}.xlsx"

    workbook = load_workbook(io.BytesIO(content))
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    assert rows[0] == ("工号", "姓名", "证件号", "开户行", "银行卡号", "应发", "实发", "期间")

    assert len(rows) == 2
    row = rows[1]
    assert row[0] == "ITEST-E-001"
    assert row[1] == "代发探针员工"
    assert row[2] == "110101199001010011"
    assert row[3] == "测试银行"
    assert row[4] == "6222020200112233445"
    assert row[5] == 5000
    assert row[6] == 4500
    assert row[7] == period
