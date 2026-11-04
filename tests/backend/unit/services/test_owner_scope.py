"""hr 数据权限接入测试（批 B3）

三部分：
1. ``TestThreePerspectiveVisibility``：真实 SQLite + 拦截器 + stub Provider
   驱动三视角裁剪——本人（SELF）/负责人（ORG_TREE 子查询）/管理员（ALL），
   含存量 NULL 归属行的可见性回归（仅管理员可见）。
2. ``TestOwnerAssignment``：创建路径归属赋值（请假/异动/审批）与
   完整性校验（重叠检查）的豁免包裹断言。
3. ``TestAdminExemption``：admin 控制器豁免包裹的行为断言
   （服务调用发生在 skip_owner_filter 上下文内）。
"""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from framework.common.ctx import Context, clear_context, set_context
from framework.database import skip_owner_filter
from framework.database.interceptors.query import (
    _owner_scope_cache_var,
    register_owner_auto_filter,
    register_tenant_auto_filter,
)
from framework.database.mixins.owner import clear_skip_owner, should_skip_owner
from framework.database.owner_scope import (
    DataScope,
    ResolvedScope,
    register_owner_scope_provider,
)
from hr.models import ApprovalRequest, EmployeeChange, LeaveRequest, LeaveType
from hr.models.employee import Employee
from hr.schemas.leave import LeaveTransferRequest
from hr.services.approval_service import approval_service
from hr.services.change_service import change_service
from hr.services.leave_request_service import leave_request_service
from iam.models import Organization, UserOrganization
from iam.services.data_scope_service import data_scope_service

TENANT = "t1"


class _ScopeStubProvider:
    """按 user_id 映射的解析替身（owner_filter 复用 iam 真实实现）"""

    def __init__(self, scopes: dict[str, ResolvedScope]):
        self._scopes = scopes

    async def resolve(self, session: AsyncSession, user_id: str) -> ResolvedScope:
        return self._scopes[user_id]

    def owner_filter(self, scope: ResolvedScope, owner_column):  # noqa: ANN001
        return data_scope_service.owner_filter(scope, owner_column)


@pytest.fixture(autouse=True)
def _reset_owner_state():
    """用例前后复位豁免标志/上下文/请求级解析缓存"""
    clear_skip_owner()
    clear_context()
    _owner_scope_cache_var.set(None)
    yield
    clear_skip_owner()
    clear_context()
    _owner_scope_cache_var.set(None)


@pytest_asyncio.fixture
async def hr_engine():
    """挂载 hr/iam schema 的内存 SQLite 引擎（拦截器真实生效）"""
    register_tenant_auto_filter()
    register_owner_auto_filter()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.execute(text("ATTACH DATABASE ':memory:' AS hr"))
        await conn.execute(text("ATTACH DATABASE ':memory:' AS iam"))
        await conn.run_sync(
            lambda sync_conn: LeaveRequest.__table__.create(
                sync_conn, checkfirst=True
            )
        )
        await conn.run_sync(
            lambda sync_conn: Organization.__table__.create(
                sync_conn, checkfirst=True
            )
        )
        await conn.run_sync(
            lambda sync_conn: UserOrganization.__table__.create(
                sync_conn, checkfirst=True
            )
        )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def scope_provider(hr_engine):
    """注册三视角替身：u-self=SELF / u-leader=ORG_TREE(org-1) / u-admin=ALL"""
    provider = _ScopeStubProvider(
        {
            "u-self": ResolvedScope(
                scope=DataScope.SELF,
                user_id="u-self",
                tenant_id=TENANT,
                user_ids=frozenset({"u-self"}),
            ),
            "u-peer": ResolvedScope(
                scope=DataScope.SELF,
                user_id="u-peer",
                tenant_id=TENANT,
                user_ids=frozenset({"u-peer"}),
            ),
            "u-leader": ResolvedScope(
                scope=DataScope.ORG_TREE,
                user_id="u-leader",
                tenant_id=TENANT,
                org_ids=frozenset({"org-1"}),
            ),
            "u-admin": ResolvedScope(scope=DataScope.ALL, user_id="u-admin", tenant_id=TENANT),
        }
    )
    register_owner_scope_provider(provider)
    yield provider
    register_owner_scope_provider(None)


async def _seed_org(session: AsyncSession, org_id: str, parent_ids: str) -> None:
    session.add(
        Organization(
            id=org_id,
            name=org_id,
            tenant_id=TENANT,
            parent_id="root",
            parent_ids=parent_ids,
        )
    )


async def _seed_membership(
    session: AsyncSession, user_id: str, org_id: str
) -> None:
    session.add(
        UserOrganization(
            user_id=user_id, organization_id=org_id, is_leader=False, tenant_id=TENANT
        )
    )


def _leave_request(request_id: str, owner_id: str | None) -> LeaveRequest:
    return LeaveRequest(
        id=request_id,
        tenant_id=TENANT,
        employee_id=f"emp-{request_id}",
        leave_type_id="lt-1",
        start_time=datetime(2026, 11, 1, 9, 0),
        end_time=datetime(2026, 11, 2, 18, 0),
        duration=2,
        reason="事由",
        status="pending",
        owner_id=owner_id,
    )


@pytest.mark.unit
class TestThreePerspectiveVisibility:
    """三视角自动裁剪（拦截器真实行为）"""

    async def _seed(self, session_factory) -> None:
        async with session_factory() as session:
            await _seed_org(session, "org-1", "root,")
            await _seed_org(session, "org-m1", "root,org-1,")
            await _seed_membership(session, "u-self", "org-m1")
            await _seed_membership(session, "u-peer", "org-m1")
            session.add(_leave_request("lr-1", "u-self"))
            session.add(_leave_request("lr-2", "u-peer"))
            session.add(_leave_request("lr-3", None))
            await session.commit()

    async def _list_ids(self, session_factory, user_id: str) -> list[str]:
        set_context(Context(user_id=user_id, tenant_id=TENANT))
        async with session_factory() as session:
            rows = (
                await session.execute(select(LeaveRequest).order_by(LeaveRequest.id))
            ).scalars().all()
        clear_context()
        return [str(row.id) for row in rows]

    async def test_self_view_sees_only_own(self, hr_engine, scope_provider):
        """本人视角（SELF）：仅本人单据，NULL 存量不可见"""
        sf = async_sessionmaker(hr_engine, class_=AsyncSession, expire_on_commit=False)
        await self._seed(sf)
        assert await self._list_ids(sf, "u-self") == ["lr-1"]

    async def test_leader_view_sees_subtree_members(
        self, hr_engine, scope_provider
    ):
        """负责人视角（ORG_TREE）：本人 ∪ 负责部门子树成员，NULL 存量不可见"""
        sf = async_sessionmaker(hr_engine, class_=AsyncSession, expire_on_commit=False)
        await self._seed(sf)
        assert await self._list_ids(sf, "u-leader") == ["lr-1", "lr-2"]

    async def test_admin_view_sees_all_including_null(
        self, hr_engine, scope_provider
    ):
        """管理员视角（ALL）：全量，含存量 NULL 归属行"""
        sf = async_sessionmaker(hr_engine, class_=AsyncSession, expire_on_commit=False)
        await self._seed(sf)
        assert await self._list_ids(sf, "u-admin") == ["lr-1", "lr-2", "lr-3"]

    async def test_skip_context_restores_full_view(self, hr_engine, scope_provider):
        """豁免包裹：任意视角下恢复全量（admin 端点语义）"""
        sf = async_sessionmaker(hr_engine, class_=AsyncSession, expire_on_commit=False)
        await self._seed(sf)
        set_context(Context(user_id="u-self", tenant_id=TENANT))
        async with sf() as session:
            with skip_owner_filter():
                rows = (
                    await session.execute(
                        select(LeaveRequest).order_by(LeaveRequest.id)
                    )
                ).scalars().all()
        clear_context()
        assert [str(row.id) for row in rows] == ["lr-1", "lr-2", "lr-3"]


# ==================== 创建路径归属赋值 ====================


def _employee(user_id: str | None) -> Employee:
    return Employee(
        id="emp-1",
        tenant_id=TENANT,
        employee_no="EMP0001",
        name="张三",
        status="regular",
        user_id=user_id,
        hire_date=date(2024, 1, 1),
    )


def _leave_type() -> LeaveType:
    return LeaveType(
        id="lt-1",
        tenant_id=TENANT,
        code="annual",
        name="年假",
        unit="day",
        paid=True,
        quota_rule="manual",
        status="enabled",
    )


_DATA = dict(
    leave_type_id="lt-1",
    start_time=datetime(2026, 11, 1, 9, 0),
    end_time=datetime(2026, 11, 3, 18, 0),
    reason="家庭事务",
)


@pytest.mark.unit
class TestOwnerAssignment:
    """创建路径归属赋值（默认归属员工）"""

    async def test_leave_submit_assigns_owner_from_employee(self):
        """请假提交：owner_id = 归属员工 user_id（本人/代创建同源）"""
        session = AsyncMock(spec=AsyncSession)
        session.get = AsyncMock(side_effect=[_employee("u-emp"), _leave_type()])

        executed: list = []

        async def _capture_overlap(stmt, *args, **kwargs):  # noqa: ANN001
            assert should_skip_owner() is True, "重叠校验应在豁免上下文中执行"
            executed.append(stmt)
            return MagicMock(scalar_one_or_none=MagicMock(return_value=None))

        session.execute = AsyncMock(side_effect=_capture_overlap)

        from hr.schemas.leave import LeaveRequestCreate

        with patch(
            "hr.services.leave_request_service.leave_service.get_or_create_balance",
            new=AsyncMock(
                return_value=MagicMock(total_quota=10, used=0, frozen=0)
            ),
        ):
            request = await leave_request_service.submit_request(
                session, "emp-1", LeaveRequestCreate(**_DATA)
            )

        assert request.owner_id == "u-emp"
        assert request.status == "pending"
        assert len(executed) == 1

    async def test_change_record_assigns_owner_from_employee(self):
        """异动流水：owner_id = 归属员工 user_id"""
        session = AsyncMock(spec=AsyncSession)
        change = await change_service.record_change(
            session,
            employee=_employee("u-9"),
            change_type="transfer",
            before_data={},
            after_data={},
            effective_date=date(2026, 12, 1),
        )
        assert change.owner_id == "u-9"

    async def test_approval_submit_prefers_applicant_user(self):
        """审批申请：applicant_user_id 显式给出时优先作为归属"""
        session = AsyncMock(spec=AsyncSession)
        session.get = AsyncMock(return_value=_employee("u-emp"))
        handler = MagicMock(validate_submit=AsyncMock())

        with (
            patch.object(approval_service, "_get_handler", return_value=handler),
            patch.object(
                approval_service, "_record_action", new=AsyncMock()
            ) as mock_action,
            patch.object(
                approval_service, "_notify_submit", new=AsyncMock()
            ),
        ):
            request = await approval_service.submit(
                session,
                biz_type="profile_change",
                applicant_employee_id="emp-1",
                title="档案变更",
                payload={"changes": []},
                applicant_user_id="u-app",
            )

        assert request.owner_id == "u-app"
        mock_action.assert_awaited_once()

    async def test_approval_submit_falls_back_to_employee_user(self):
        """审批申请：applicant_user_id 缺失时回退归属员工 user_id"""
        session = AsyncMock(spec=AsyncSession)
        session.get = AsyncMock(return_value=_employee("u-emp"))
        handler = MagicMock(validate_submit=AsyncMock())

        with (
            patch.object(approval_service, "_get_handler", return_value=handler),
            patch.object(approval_service, "_record_action", new=AsyncMock()),
            patch.object(approval_service, "_notify_submit", new=AsyncMock()),
        ):
            request = await approval_service.submit(
                session,
                biz_type="profile_change",
                applicant_employee_id="emp-1",
                title="档案变更",
                payload={"changes": []},
                applicant_user_id=None,
            )

        assert request.owner_id == "u-emp"


# ==================== admin 控制器豁免包裹 ====================


@pytest.mark.unit
class TestAdminExemption:
    """admin 端点全量视角：服务调用发生在 skip_owner_filter 上下文内"""

    async def test_leave_admin_list_wraps_skip_owner(self):
        from hr.controllers.admin.leave_controller import list_leave_requests

        async def fake_list(session, **kwargs):
            assert should_skip_owner() is True
            return {"total": 0, "items": []}

        with patch.object(leave_request_service, "list_requests", fake_list):
            response = await list_leave_requests(
                status=None,
                leave_type_id=None,
                org_id=None,
                keyword=None,
                date_from=None,
                date_to=None,
                page=1,
                page_size=20,
                session=MagicMock(),
                _=None,
            )
        assert response is not None

    async def test_change_admin_get_wraps_skip_owner(self):
        from hr.controllers.admin.change_controller import get_change

        async def fake_get(session, change_id):
            assert should_skip_owner() is True
            change = EmployeeChange(
                employee_id="e1",
                change_type="transfer",
                before_data={},
                after_data={},
                effective_date=date(2026, 12, 1),
                operator_id="op",
                owner_id="u-9",
            )
            change.id = "chg-1"
            return change

        with patch.object(change_service, "get_change", fake_get):
            response = await get_change(
                change_id="chg-1", user_id="u-admin", _perm=None, session=MagicMock()
            )
        assert response is not None

    async def test_approval_admin_detail_wraps_skip_owner(self):
        from hr.controllers.admin.approval_request_controller import (
            get_approval_request,
        )

        async def fake_detail(session, request_id):
            assert should_skip_owner() is True
            return {"id": request_id}

        with patch.object(approval_service, "get_detail", fake_detail):
            response = await get_approval_request(
                request_id="req-1", session=MagicMock(), _=None
            )
        assert response is not None


# ==================== 移交（批 D1） ====================


@pytest.mark.unit
class TestDataTransfer:
    """移交端到端语义：可见性随 owner 转移 + owner 更新 + 审计留痕 + 权限门声明"""

    async def test_leave_transfer_moves_visibility(self, hr_engine, scope_provider):
        """转移后新归属人（SELF）可见，原归属人不可见"""
        sf = async_sessionmaker(hr_engine, class_=AsyncSession, expire_on_commit=False)
        async with sf() as session:
            await _seed_org(session, "org-1", "root,")
            await _seed_org(session, "org-m1", "root,org-1,")
            await _seed_membership(session, "u-self", "org-m1")
            await _seed_membership(session, "u-peer", "org-m1")
            session.add(_leave_request("lr-1", "u-self"))
            await session.commit()

        set_context(Context(user_id="u-admin", tenant_id=TENANT))
        async with sf() as session:
            with skip_owner_filter():
                with patch(
                    "hr.services.leave_request_service.validate_transfer_target",
                    new=AsyncMock(),
                ):
                    await leave_request_service.transfer(
                        session, "lr-1", new_owner_id="u-peer"
                    )
                await session.commit()
        clear_context()

        async with sf() as session:
            set_context(Context(user_id="u-peer", tenant_id=TENANT))
            peer_rows = (
                await session.execute(select(LeaveRequest))
            ).scalars().all()
            clear_context()
            set_context(Context(user_id="u-self", tenant_id=TENANT))
            self_rows = (
                await session.execute(select(LeaveRequest))
            ).scalars().all()
        clear_context()
        assert [str(r.id) for r in peer_rows] == ["lr-1"]
        assert [str(r.id) for r in self_rows] == []

    async def test_change_transfer_updates_owner(self):
        """异动移交：owner_id 更新为目标用户"""
        session = AsyncMock(spec=AsyncSession)
        change = EmployeeChange(
            employee_id="e1",
            change_type="transfer",
            before_data={},
            after_data={},
            effective_date=date(2026, 12, 1),
            operator_id="op",
            owner_id="u-old",
        )
        change.id = "chg-1"
        session.get = AsyncMock(return_value=change)
        with patch(
            "hr.services.change_service.validate_transfer_target", new=AsyncMock()
        ):
            result = await change_service.transfer_change(
                session, "chg-1", new_owner_id="u-new"
            )
        assert result.owner_id == "u-new"

    async def test_approval_transfer_updates_owner(self):
        """审批请求移交：owner_id 更新为目标用户"""
        session = AsyncMock(spec=AsyncSession)
        request = ApprovalRequest(
            biz_type="profile_change",
            applicant_employee_id="emp-1",
            title="档案变更",
            status="pending",
            owner_id="u-old",
        )
        request.id = "req-1"
        session.get = AsyncMock(return_value=request)
        with patch(
            "hr.services.approval_service.validate_transfer_target", new=AsyncMock()
        ):
            result = await approval_service.transfer_request(
                session, "req-1", new_owner_id="u-new"
            )
        assert result.owner_id == "u-new"

    async def test_leave_transfer_endpoint_writes_audit_trail(self):
        """移交端点：审计留痕含 before/after owner 与操作人"""
        from hr.controllers.admin.leave_controller import transfer_leave_request

        request = _leave_request("lr-1", "u-old")
        session = AsyncMock(spec=AsyncSession)
        session.get = AsyncMock(return_value=request)

        audit = MagicMock()
        audit.create_audit_log = AsyncMock()
        with (
            patch(
                "hr.services.leave_request_service.validate_transfer_target",
                new=AsyncMock(),
            ),
            patch(
                "hr.controllers.admin.leave_controller.get_iam_client",
                return_value=audit,
            ),
        ):
            await transfer_leave_request(
                request_id="lr-1",
                data=LeaveTransferRequest(owner_id="u-new"),
                operator_id="u-admin",
                session=session,
                _=None,
            )

        kwargs = audit.create_audit_log.await_args.kwargs
        assert kwargs["operation_type"] == "transfer"
        assert kwargs["before_data"] == {"owner_id": "u-old"}
        assert kwargs["after_data"] == {"owner_id": "u-new"}
        assert kwargs["detail"] == {"operator_id": "u-admin"}

    async def test_transfer_endpoints_declare_transfer_permission(self):
        """权限门声明：三个移交端点挂各自 transfer 权限码"""
        import inspect

        from hr.controllers.admin.approval_request_controller import (
            transfer_approval_request,
        )
        from hr.controllers.admin.change_controller import transfer_change
        from hr.controllers.admin.leave_controller import transfer_leave_request

        assert "hr:leave:transfer" in inspect.getsource(transfer_leave_request)
        assert "hr:employee_change:transfer" in inspect.getsource(transfer_change)
        assert "hr:approval:transfer" in inspect.getsource(transfer_approval_request)
