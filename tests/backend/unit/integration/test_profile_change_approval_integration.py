"""ESS 档案变更审批流集成测试（二期 F.1）：self_editable 定义 → 提交变更申请
（载荷校验）→ 审批通过应用 EAV 值 + 流水留痕；驳回不应用；非自助属性提交被拒。

真库直跑（hr schema），事务内断言不 commit（回滚零清理）。
"""

from datetime import date, timedelta
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from framework.common.ctx import set_user
from framework.common.exceptions import BadRequestError
from framework.tenant.context import TenantContext
from hr.models import ApprovalAction, ApprovalRequest, Employee, EmployeeAttributeValue
from hr.services.approval_service import approval_service

pytestmark = pytest.mark.integration

TENANT = "itest-hr-approval"


@pytest_asyncio.fixture()
async def session(postgres_engine) -> AsyncIterator[tuple[AsyncSession, str, str]]:
    from framework.database.events.tenant import register_tenant_events
    from framework.database.interceptors.query import register_tenant_auto_filter
    from hr.services.eav_service import eav_service

    register_tenant_auto_filter()
    register_tenant_events()
    TenantContext.set_tenant_id(TENANT)
    set_user(user_id="itest-operator", tenant_id=TENANT)
    maker = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with maker() as sess:
        employee = Employee(
            tenant_id=TENANT,
            employee_no="ITEST-AP-001",
            name="审批探针员工",
            status="regular",
            hire_date=date.today() - timedelta(days=100),
        )
        sess.add(employee)
        await sess.flush()
        employee_id = str(employee.id)

        group = await eav_service.create_group(
            sess, code="itest-ap-grp", name="审批探针组", sort=99
        )
        editable = await eav_service.create_definition(
            sess,
            group_id=str(group.id),
            name="家庭住址（探针）",
            data_type="string",
            ext_data={"self_editable": True},
        )
        locked = await eav_service.create_definition(
            sess,
            group_id=str(group.id),
            name="证件号（探针）",
            data_type="string",
        )
        await sess.flush()
        yield sess, employee_id, f"{editable.id}|{locked.id}"
        await sess.rollback()
    TenantContext.clear()


@pytest.mark.asyncio
async def test_profile_change_submit_approve_apply_and_reject(
    session: tuple[AsyncSession, str, str],
):
    """提交 → 通过应用变更 + 留痕；驳回不应用；非自助属性提交被拒"""
    sess, employee_id, ids = session
    editable_id, locked_id = ids.split("|")

    # 非自助属性：提交即拒（self_editable 校验）
    with pytest.raises(BadRequestError, match="不支持自助变更"):
        await approval_service.submit(
            sess,
            biz_type="profile_change",
            applicant_employee_id=employee_id,
            applicant_user_id="itest-applicant",
            title="改证件号",
            payload={"changes": [{"definition_id": locked_id, "new_value": "110101"}]},
        )

    # 提交变更申请（原值朝阳区 → 海淀区）
    request = await approval_service.submit(
        sess,
        biz_type="profile_change",
        applicant_employee_id=employee_id,
        applicant_user_id="itest-applicant",
        title="更新家庭住址",
        payload={"changes": [{"definition_id": editable_id, "new_value": "海淀区"}]},
    )
    assert request.status == "pending"

    actions = (
        await sess.execute(
            select(ApprovalAction).where(ApprovalAction.request_id == str(request.id))
        )
    ).scalars().all()
    assert [action.action for action in actions] == ["submit"]

    # 驳回：意见必填 + 终态不应用变更
    rejected = await approval_service.reject(
        sess, str(request.id), approver_id="itest-approver", comment="信息待确认"
    )
    assert rejected.status == "rejected"
    assert rejected.approve_comment == "信息待确认"
    row = (
        await sess.execute(
            select(EmployeeAttributeValue).where(
                EmployeeAttributeValue.employee_id == employee_id,
                EmployeeAttributeValue.definition_id == editable_id,
            )
        )
    ).scalar_one_or_none()
    assert row is None

    # 已终态不可再审批
    from framework.common.exceptions import ConflictError

    with pytest.raises(ConflictError, match="不可审批"):
        await approval_service.approve(
            sess, str(request.id), approver_id="itest-approver"
        )

    # 重新提交 → 通过应用 EAV 值
    second = await approval_service.submit(
        sess,
        biz_type="profile_change",
        applicant_employee_id=employee_id,
        applicant_user_id="itest-applicant",
        title="再次申请家庭住址",
        payload={"changes": [{"definition_id": editable_id, "new_value": "海淀区"}]},
    )
    approved = await approval_service.approve(
        sess, str(second.id), approver_id="itest-approver", comment="同意"
    )
    assert approved.status == "approved"
    assert approved.approver_id == "itest-approver"

    row = (
        await sess.execute(
            select(EmployeeAttributeValue).where(
                EmployeeAttributeValue.employee_id == employee_id,
                EmployeeAttributeValue.definition_id == editable_id,
            )
        )
    ).scalar_one()
    assert row.value == "海淀区"

    actions = (
        await sess.execute(
            select(ApprovalAction)
            .where(ApprovalAction.request_id == str(second.id))
            .order_by(ApprovalAction.created_at)
        )
    ).scalars().all()
    assert [action.action for action in actions] == ["submit", "approve"]
    assert all(action.actor_id in ("itest-applicant", "itest-approver") for action in actions)


@pytest.mark.asyncio
async def test_profile_change_invalid_payload_rejected(
    session: tuple[AsyncSession, str, str],
):
    """空变更集 / 缺 definition_id / 属性不存在均拒绝"""
    sess, employee_id, ids = session
    editable_id = ids.split("|")[0]

    with pytest.raises(BadRequestError, match="changes"):
        await approval_service.submit(
            sess,
            biz_type="profile_change",
            applicant_employee_id=employee_id,
            applicant_user_id="itest-applicant",
            title="空变更",
            payload={"changes": []},
        )

    with pytest.raises(BadRequestError, match="definition_id"):
        await approval_service.submit(
            sess,
            biz_type="profile_change",
            applicant_employee_id=employee_id,
            applicant_user_id="itest-applicant",
            title="缺定义",
            payload={"changes": [{"new_value": "x"}]},
        )

    with pytest.raises(Exception, match="不存在"):
        await approval_service.submit(
            sess,
            biz_type="profile_change",
            applicant_employee_id=employee_id,
            applicant_user_id="itest-applicant",
            title="幽灵定义",
            payload={"changes": [{"definition_id": "def-ghost", "new_value": "x"}]},
        )
