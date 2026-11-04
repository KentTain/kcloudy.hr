"""员工 EAV 流集成测试（§8.1）：定义 → 实例值 → 自助渲染（读取合并视图）。

真库直跑（hr schema），事务内断言不 commit（session 关闭回滚，零清理负担）；
跨租户断言用独立探针租户 + 独立会话验证定义隔离。属性值外键指向 employees，
探针员工须真实建行；跨会话用例显式 commit，fixture 按表清理。
"""

from datetime import date, timedelta
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from framework.tenant.context import TenantContext
from hr.models.employee import (
    Employee,
    EmployeeAttributeValue,
    EmployeeFieldDefinition,
    EmployeeFieldGroup,
)
from hr.services.eav_service import eav_service

pytestmark = pytest.mark.integration

TENANT = "itest-hr-eav"
TENANT_B = "itest-hr-eav-b"


@pytest_asyncio.fixture()
async def _cleanup(postgres_engine):
    yield
    async with postgres_engine.begin() as conn:
        for table in (
            EmployeeAttributeValue.__table__,
            EmployeeFieldDefinition.__table__,
            EmployeeFieldGroup.__table__,
        ):
            for tenant in (TENANT, TENANT_B):
                await conn.execute(table.delete().where(table.c.tenant_id == tenant))
        # 跨会话用例显式 commit 过探针员工行（属性值外键依赖），需一并清理
        await conn.execute(Employee.__table__.delete().where(Employee.__table__.c.tenant_id == TENANT))


@pytest_asyncio.fixture()
async def session(postgres_engine) -> AsyncIterator[tuple[AsyncSession, str]]:
    from framework.database.events.tenant import register_tenant_events
    from framework.database.interceptors.query import register_tenant_auto_filter

    register_tenant_auto_filter()
    register_tenant_events()
    TenantContext.set_tenant_id(TENANT)
    maker = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with maker() as sess:
        employee = Employee(
            tenant_id=TENANT,
            employee_no="ITEST-E-001",
            name="EAV 探针员工",
            status="regular",
            hire_date=date.today() - timedelta(days=100),
        )
        sess.add(employee)
        await sess.flush()
        yield sess, str(employee.id)
        await sess.rollback()
    TenantContext.clear()


@pytest.mark.asyncio
async def test_eav_define_save_and_render_flow(session: tuple[AsyncSession, str]):
    """组→定义→写值→覆盖更新→合并视图渲染（未配置值回 None）"""
    sess, employee_id = session
    group = await eav_service.create_group(sess, code="itest-eav-grp", name="集成探针组", sort=99)
    definition = await eav_service.create_definition(
        sess, group_id=str(group.id), name="紧急联系人", data_type="string", can_edit=True, sort=1
    )
    other = await eav_service.create_definition(
        sess, group_id=str(group.id), name="血型", data_type="string", can_edit=True, sort=2
    )

    written = await eav_service.save_employee_attributes(
        sess, employee_id, {str(definition.id): "李四"}
    )
    assert written == 1

    # 自助渲染口径：定义全量 + 本人值合并（未配置回 None）
    attributes = await eav_service.get_employee_attributes(sess, employee_id)
    by_name = {item["name"]: item for item in attributes}
    assert by_name["紧急联系人"]["value"] == "李四"
    assert by_name["血型"]["value"] is None

    # 覆盖更新走 upsert
    written = await eav_service.save_employee_attributes(
        sess, employee_id, {str(definition.id): "王五", str(other.id): "A"}
    )
    assert written == 2
    attributes = await eav_service.get_employee_attributes(sess, employee_id)
    by_name = {item["name"]: item for item in attributes}
    assert by_name["紧急联系人"]["value"] == "王五"
    assert by_name["血型"]["value"] == "A"


@pytest.mark.asyncio
async def test_eav_values_survive_across_sessions_and_tenant_isolated(postgres_engine, _cleanup):
    """实例值持久化跨会话可读；他租户不可见该租户的定义"""
    from framework.database.events.tenant import register_tenant_events
    from framework.database.interceptors.query import register_tenant_auto_filter

    register_tenant_auto_filter()
    register_tenant_events()
    TenantContext.set_tenant_id(TENANT)
    maker = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with maker() as sess:
        employee = Employee(
            tenant_id=TENANT,
            employee_no="ITEST-E-002",
            name="EAV 隔离探针员工",
            status="regular",
            hire_date=date.today() - timedelta(days=100),
        )
        sess.add(employee)
        await sess.flush()
        employee_id = str(employee.id)
        group = await eav_service.create_group(sess, code="itest-eav-grp2", name="隔离探针组", sort=99)
        definition = await eav_service.create_definition(
            sess, group_id=str(group.id), name="籍贯", data_type="string", can_edit=True
        )
        await eav_service.save_employee_attributes(sess, employee_id, {str(definition.id): "杭州"})
        await sess.commit()
        group_id = str(group.id)

    # 新会话（同租户）：定义与值均可读
    async with maker() as sess:
        rows = (
            await sess.execute(
                select(EmployeeFieldDefinition).where(EmployeeFieldDefinition.group_id == group_id)
            )
        ).scalars().all()
        assert len(rows) == 1
        attributes = await eav_service.get_employee_attributes(sess, employee_id)
        assert attributes[0]["value"] == "杭州"

    # 他租户：组不可见（租户自动过滤）
    TenantContext.set_tenant_id(TENANT_B)
    try:
        async with maker() as sess:
            rows = (
                await sess.execute(select(EmployeeFieldGroup).where(EmployeeFieldGroup.code == "itest-eav-grp2"))
            ).scalars().all()
            assert rows == []
    finally:
        TenantContext.clear()
