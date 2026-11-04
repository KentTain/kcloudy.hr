"""审批服务单元测试

覆盖：profile_change handler 提交校验（空 changes/self_editable 门控/定义存在
性/值类型）、submit 校验链（在职/未知 biz_type）、状态机（通过=handler 应用
EAV 值+留痕、驳回意见必填、撤销仅本人待审批）、终态不可再审批。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError
from framework.tenant.context import TenantContext

from hr.models import (
    ApprovalRequest,
    Employee,
    EmployeeAttributeValue,
    EmployeeFieldDefinition,
)
from hr.services.approval_service import (
    ProfileChangeHandler,
    approval_service,
)


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

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
    session.get = AsyncMock(
        side_effect=lambda model, pk: (get_map or {}).get((model.__name__, str(pk)))
    )
    session.execute = AsyncMock(
        side_effect=list(execute_results) if execute_results else []
    )
    return session


def _employee(**overrides) -> Employee:
    defaults = dict(
        id="emp-1", tenant_id="t-1", employee_no="EMP0001",
        name="张三", status="regular",
    )
    defaults.update(overrides)
    return Employee(**defaults)


def _definition(**overrides) -> EmployeeFieldDefinition:
    defaults = dict(
        id="def-1", tenant_id="t-1", group_id="grp-1", name="手机号",
        data_type="string", ext_data={"self_editable": True},
        is_require=False, can_edit=True, sort=1,
    )
    defaults.update(overrides)
    return EmployeeFieldDefinition(**defaults)


def _request(**overrides) -> ApprovalRequest:
    defaults = dict(
        id="req-1", tenant_id="t-1", biz_type="profile_change",
        applicant_employee_id="emp-1", title="档案信息变更申请",
        payload={"changes": [{"definition_id": "def-1", "new_value": "13912345678"}]},
        status="pending",
    )
    defaults.update(overrides)
    return ApprovalRequest(**defaults)


def _changes_payload(**overrides) -> dict:
    payload = {"changes": [{"definition_id": "def-1", "new_value": "13912345678"}]}
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def _tenant_context():
    TenantContext.set_tenant_id("t-1")
    yield
    TenantContext.clear()


class TestProfileChangeHandler:
    """profile_change 提交载荷校验"""

    @pytest.mark.asyncio
    async def test_empty_changes_rejected(self):
        session = _mock_session()
        with pytest.raises(BadRequestError, match="changes"):
            await ProfileChangeHandler().validate_submit(session, {"changes": []})

    @pytest.mark.asyncio
    async def test_changes_not_list_rejected(self):
        session = _mock_session()
        with pytest.raises(BadRequestError, match="列表"):
            await ProfileChangeHandler().validate_submit(session, {"changes": "x"})

    @pytest.mark.asyncio
    async def test_missing_definition_id_rejected(self):
        session = _mock_session()
        with pytest.raises(BadRequestError, match="definition_id"):
            await ProfileChangeHandler().validate_submit(
                session, {"changes": [{"new_value": "x"}]}
            )

    @pytest.mark.asyncio
    async def test_definition_not_found(self):
        session = _mock_session()
        with pytest.raises(NotFoundError, match="属性定义"):
            await ProfileChangeHandler().validate_submit(session, _changes_payload())

    @pytest.mark.asyncio
    async def test_non_self_editable_rejected(self):
        session = _mock_session(
            get_map={("EmployeeFieldDefinition", "def-1"): _definition(ext_data={})}
        )
        with pytest.raises(BadRequestError, match="不支持自助变更"):
            await ProfileChangeHandler().validate_submit(session, _changes_payload())

    @pytest.mark.asyncio
    async def test_invalid_value_rejected(self):
        session = _mock_session(
            get_map={
                ("EmployeeFieldDefinition", "def-1"): _definition(data_type="integer")
            }
        )
        with pytest.raises(BadRequestError, match="数值"):
            await ProfileChangeHandler().validate_submit(
                session,
                {"changes": [{"definition_id": "def-1", "new_value": "abc"}]},
            )

    @pytest.mark.asyncio
    async def test_valid_payload_passes(self):
        session = _mock_session(
            get_map={("EmployeeFieldDefinition", "def-1"): _definition()}
        )
        await ProfileChangeHandler().validate_submit(session, _changes_payload())


class TestSubmit:
    """提交校验链"""

    @pytest.mark.asyncio
    async def test_unknown_biz_type_rejected(self):
        session = _mock_session()
        with pytest.raises(BadRequestError, match="未知审批业务类型"):
            await approval_service.submit(
                session, biz_type="leave", applicant_employee_id="emp-1",
                title="t", payload={},
            )

    @pytest.mark.asyncio
    async def test_employee_not_found(self):
        session = _mock_session()
        with pytest.raises(NotFoundError, match="员工"):
            await approval_service.submit(
                session, biz_type="profile_change", applicant_employee_id="emp-404",
                title="t", payload=_changes_payload(),
            )

    @pytest.mark.asyncio
    async def test_offboarded_rejected(self):
        session = _mock_session(
            get_map={("Employee", "emp-1"): _employee(status="offboarded")}
        )
        with pytest.raises(ConflictError, match="在职"):
            await approval_service.submit(
                session, biz_type="profile_change", applicant_employee_id="emp-1",
                title="t", payload=_changes_payload(),
            )

    @pytest.mark.asyncio
    async def test_success_creates_pending_and_submit_action(self):
        session = _mock_session(
            get_map={
                ("Employee", "emp-1"): _employee(),
                ("EmployeeFieldDefinition", "def-1"): _definition(),
            }
        )
        request = await approval_service.submit(
            session, biz_type="profile_change", applicant_employee_id="emp-1",
            applicant_user_id="u-1", title="档案信息变更申请",
            payload=_changes_payload(),
        )
        assert request.status == "pending"
        assert request.tenant_id == "t-1"
        assert request.biz_type == "profile_change"
        actions = [a for a in session._added if isinstance(a, type(request)) is False]
        submit_actions = [a for a in session._added if getattr(a, "action", None) == "submit"]
        assert len(submit_actions) == 1
        assert submit_actions[0].actor_id == "u-1"
        assert submit_actions[0].request_id == str(request.id)


class TestApprove:
    """审批通过"""

    @pytest.mark.asyncio
    async def test_non_pending_rejected(self):
        session = _mock_session(
            get_map={("ApprovalRequest", "req-1"): _request(status="approved")}
        )
        with pytest.raises(ConflictError, match="不可审批"):
            await approval_service.approve(session, "req-1", approver_id="u-1")

    @pytest.mark.asyncio
    async def test_approve_applies_eav_value_and_records_action(self):
        request = _request()
        session = _mock_session(
            get_map={
                ("ApprovalRequest", "req-1"): request,
                ("EmployeeFieldDefinition", "def-1"): _definition(),
            },
            execute_results=[_FakeResult(rows=[])],  # 无存量属性值行
        )
        result = await approval_service.approve(
            session, "req-1", approver_id="u-1", comment="同意"
        )
        assert result.status == "approved"
        assert result.approver_id == "u-1"
        # EAV 值行新建并写入序列化值
        value_rows = [
            a for a in session._added if isinstance(a, EmployeeAttributeValue)
        ]
        assert len(value_rows) == 1
        assert value_rows[0].value == "13912345678"
        assert value_rows[0].employee_id == "emp-1"
        # 通过流水留痕
        approve_actions = [a for a in session._added if getattr(a, "action", None) == "approve"]
        assert len(approve_actions) == 1
        assert approve_actions[0].actor_id == "u-1"

    @pytest.mark.asyncio
    async def test_approve_updates_existing_value_row(self):
        request = _request()
        existing = EmployeeAttributeValue(
            employee_id="emp-1", definition_id="def-1", value="13800000000"
        )
        session = _mock_session(
            get_map={
                ("ApprovalRequest", "req-1"): request,
                ("EmployeeFieldDefinition", "def-1"): _definition(),
            },
            execute_results=[_FakeResult(rows=[existing])],
        )
        await approval_service.approve(session, "req-1", approver_id="u-1")
        assert existing.value == "13912345678"

    @pytest.mark.asyncio
    async def test_handler_error_propagates_before_status_change(self):
        request = _request()
        session = _mock_session(
            get_map={
                ("ApprovalRequest", "req-1"): request,
                ("EmployeeFieldDefinition", "def-1"): None,  # 定义被删
            },
        )
        with pytest.raises(NotFoundError):
            await approval_service.approve(session, "req-1", approver_id="u-1")
        assert request.status == "pending"  # 状态未变（事务内整体回滚由调用方保证）


class TestRejectAndCancel:
    """驳回与撤销"""

    @pytest.mark.asyncio
    async def test_reject_requires_comment(self):
        session = _mock_session()
        with pytest.raises(BadRequestError, match="意见"):
            await approval_service.reject(
                session, "req-1", approver_id="u-1", comment="  "
            )

    @pytest.mark.asyncio
    async def test_reject_records_action(self):
        session = _mock_session(
            get_map={("ApprovalRequest", "req-1"): _request()}
        )
        result = await approval_service.reject(
            session, "req-1", approver_id="u-1", comment="材料不全"
        )
        assert result.status == "rejected"
        assert result.approve_comment == "材料不全"
        reject_actions = [a for a in session._added if getattr(a, "action", None) == "reject"]
        assert len(reject_actions) == 1
        assert reject_actions[0].comment == "材料不全"

    @pytest.mark.asyncio
    async def test_cancel_only_own(self):
        session = _mock_session(
            get_map={("ApprovalRequest", "req-1"): _request(applicant_employee_id="emp-other")}
        )
        with pytest.raises(ConflictError, match="本人"):
            await approval_service.cancel(session, "req-1", operator_employee_id="emp-1")

    @pytest.mark.asyncio
    async def test_cancel_processed_rejected(self):
        session = _mock_session(
            get_map={("ApprovalRequest", "req-1"): _request(status="approved")}
        )
        with pytest.raises(ConflictError, match="待审批"):
            await approval_service.cancel(session, "req-1", operator_employee_id="emp-1")

    @pytest.mark.asyncio
    async def test_cancel_records_action(self):
        session = _mock_session(
            get_map={("ApprovalRequest", "req-1"): _request(applicant_user_id="u-9")}
        )
        result = await approval_service.cancel(session, "req-1", operator_employee_id="emp-1")
        assert result.status == "cancelled"
        cancel_actions = [a for a in session._added if getattr(a, "action", None) == "cancel"]
        assert len(cancel_actions) == 1


class TestNotify:
    """审批通知接统一底座 notify()：提交→审批池 / 结果→申请人 / 失败不阻断"""

    @pytest.mark.asyncio
    async def test_submit_notifies_approver_pool(self):
        session = _mock_session(
            get_map={
                ("Employee", "emp-1"): _employee(),
                ("EmployeeFieldDefinition", "def-1"): _definition(),
            },
            execute_results=[_FakeResult(rows=["user-1", "user-2"])],
        )
        with patch(
            "framework.notification.dispatcher.notify", new=AsyncMock()
        ) as notify:
            request = await approval_service.submit(
                session, biz_type="profile_change", applicant_employee_id="emp-1",
                applicant_user_id="u-1", title="档案信息变更申请",
                payload=_changes_payload(),
            )
        notify.assert_awaited_once()
        kwargs = notify.await_args.kwargs
        assert kwargs["recipients"] == ["user-1", "user-2"]
        assert kwargs["notification_type"] == "hr_approval_submitted"
        assert kwargs["title"] == "新审批申请待处理"
        assert "档案信息变更申请" in kwargs["content"]
        assert kwargs["link"] == "/hr/approvals"
        assert request.status == "pending"

    @pytest.mark.asyncio
    async def test_submit_without_pool_members_skips_notify(self):
        session = _mock_session(
            get_map={
                ("Employee", "emp-1"): _employee(),
                ("EmployeeFieldDefinition", "def-1"): _definition(),
            },
            execute_results=[_FakeResult(rows=[])],
        )
        with patch(
            "framework.notification.dispatcher.notify", new=AsyncMock()
        ) as notify:
            await approval_service.submit(
                session, biz_type="profile_change", applicant_employee_id="emp-1",
                applicant_user_id="u-1", title="档案信息变更申请",
                payload=_changes_payload(),
            )
        notify.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_approve_notifies_applicant_with_comment(self):
        definition = _definition()
        session = _mock_session(
            get_map={
                ("ApprovalRequest", "req-1"): _request(
                    applicant_user_id="u-9", approve_comment=None
                ),
                ("EmployeeFieldDefinition", "def-1"): definition,
            },
            execute_results=[_FakeResult(rows=[])],  # 无既有 EAV 值行
        )
        with patch(
            "framework.notification.dispatcher.notify", new=AsyncMock()
        ) as notify:
            result = await approval_service.approve(
                session, "req-1", approver_id="u-1", comment="同意"
            )
        assert result.status == "approved"
        notify.assert_awaited_once()
        kwargs = notify.await_args.kwargs
        assert kwargs["recipients"] == ["u-9"]
        assert kwargs["notification_type"] == "hr_approval_approved"
        assert "已通过" in kwargs["content"]
        assert "同意" in kwargs["content"]

    @pytest.mark.asyncio
    async def test_reject_notifies_applicant(self):
        session = _mock_session(
            get_map={
                ("ApprovalRequest", "req-1"): _request(applicant_user_id="u-9")
            }
        )
        with patch(
            "framework.notification.dispatcher.notify", new=AsyncMock()
        ) as notify:
            result = await approval_service.reject(
                session, "req-1", approver_id="u-1", comment="材料不全"
            )
        assert result.status == "rejected"
        kwargs = notify.await_args.kwargs
        assert kwargs["notification_type"] == "hr_approval_rejected"
        assert "已驳回" in kwargs["content"]
        assert "材料不全" in kwargs["content"]

    @pytest.mark.asyncio
    async def test_notify_failure_does_not_block(self):
        session = _mock_session(
            get_map={
                ("Employee", "emp-1"): _employee(),
                ("EmployeeFieldDefinition", "def-1"): _definition(),
            },
            execute_results=[_FakeResult(rows=["user-1"])],
        )
        with patch(
            "framework.notification.dispatcher.notify",
            new=AsyncMock(side_effect=RuntimeError("notify down")),
        ):
            request = await approval_service.submit(
                session, biz_type="profile_change", applicant_employee_id="emp-1",
                applicant_user_id="u-1", title="档案信息变更申请",
                payload=_changes_payload(),
            )
        assert request.status == "pending"
