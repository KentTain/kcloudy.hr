"""统一审批流服务：submit/approve/reject/cancel + 流水留痕 + biz handler 注册表

池模式审批（具备 hr:approval:approve 权限者处理，不预指定审批人）；biz_type 对应
handler 负责提交载荷校验与通过后应用业务变更，handler 异常整体回滚保持 pending；
终态只读。新业务类型实现 validate_submit/apply 协议后经 register_handler 注册。
"""

from datetime import datetime
from typing import Any

from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.ctx import get_tenant_id
from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError

from hr.common.transfer import validate_transfer_target

from hr.models import (
    ApprovalAction,
    ApprovalRequest,
    Employee,
    EmployeeAttributeValue,
    EmployeeFieldDefinition,
)
from hr.services.eav_service import validate_and_serialize_value

_logger = logger.bind(name=__name__)

_ACTIVE_EMPLOYEE_STATUSES = ("probation", "regular", "intern")


class ProfileChangeHandler:
    """档案变更申请 handler：员工自助提交属性值变更集，通过时应用 EAV 值。"""

    biz_type = "profile_change"

    async def validate_submit(self, session: AsyncSession, payload: dict) -> None:
        changes = payload.get("changes") if isinstance(payload, dict) else None
        if not changes or not isinstance(changes, list):
            raise BadRequestError("档案变更申请须包含非空 changes 列表")
        for item in changes:
            definition_id = item.get("definition_id") if isinstance(item, dict) else None
            if not definition_id:
                raise BadRequestError("变更项缺少 definition_id")
            definition = await session.get(EmployeeFieldDefinition, definition_id)
            if not definition:
                raise NotFoundError(f"属性定义 {definition_id} 不存在")
            if not (definition.ext_data or {}).get("self_editable"):
                raise BadRequestError(f"属性 {definition.name} 不支持自助变更")
            validate_and_serialize_value(
                definition.name,
                definition.data_type,
                definition.ext_data,
                item.get("new_value"),
            )

    async def apply(self, session: AsyncSession, request: ApprovalRequest) -> None:
        changes = (request.payload or {}).get("changes") or []
        for item in changes:
            definition = await session.get(EmployeeFieldDefinition, item["definition_id"])
            if not definition:
                raise NotFoundError(f"属性定义 {item['definition_id']} 不存在")
            serialized = validate_and_serialize_value(
                definition.name,
                definition.data_type,
                definition.ext_data,
                item.get("new_value"),
            )
            row = (
                await session.execute(
                    select(EmployeeAttributeValue)
                    .where(
                        EmployeeAttributeValue.employee_id == request.applicant_employee_id,
                        EmployeeAttributeValue.definition_id == definition.id,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                if serialized is None:
                    continue
                row = EmployeeAttributeValue(
                    employee_id=str(request.applicant_employee_id),
                    definition_id=str(definition.id),
                )
                session.add(row)
            row.value = serialized
        await session.flush()
        _logger.info(f"档案变更已应用 request={request.id} employee={request.applicant_employee_id}")


_HANDLERS: dict[str, Any] = {}


def register_handler(handler: Any) -> None:
    """注册 biz_type handler（validate_submit/apply 协议）。"""
    _HANDLERS[handler.biz_type] = handler


register_handler(ProfileChangeHandler())


class ApprovalService:
    """审批请求业务（审批动作需 hr:approval:approve；驳回意见必填）"""

    async def list_requests(
        self,
        session: AsyncSession,
        *,
        biz_type: str | None = None,
        status: str | None = None,
        applicant_employee_id: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        conditions = []
        if biz_type:
            conditions.append(ApprovalRequest.biz_type == biz_type)
        if status:
            conditions.append(ApprovalRequest.status == status)
        if applicant_employee_id:
            conditions.append(ApprovalRequest.applicant_employee_id == applicant_employee_id)
        if keyword:
            like = f"%{keyword}%"
            conditions.append(
                or_(Employee.name.ilike(like), Employee.employee_no.ilike(like))
            )

        total = (
            await session.execute(
                select(func.count(ApprovalRequest.id))
                .join(Employee, ApprovalRequest.applicant_employee_id == Employee.id)
                .where(*conditions)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(ApprovalRequest, Employee)
                .join(Employee, ApprovalRequest.applicant_employee_id == Employee.id)
                .where(*conditions)
                .order_by(ApprovalRequest.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return {
            "total": total,
            "items": [self.to_response(request, employee) for request, employee in rows],
        }

    async def get_detail(self, session: AsyncSession, request_id: str) -> dict:
        request = await self._get_request(session, request_id)
        employee = await session.get(Employee, request.applicant_employee_id)
        actions = (
            await session.execute(
                select(ApprovalAction)
                .where(ApprovalAction.request_id == request_id)
                .order_by(ApprovalAction.created_at.asc())
            )
        ).scalars().all()
        response = self.to_response(request, employee)
        detail = response.model_dump()
        detail["actions"] = [
            {
                "id": str(action.id),
                "action": action.action,
                "actor_id": action.actor_id,
                "comment": action.comment,
                "created_at": action.created_at,
            }
            for action in actions
        ]
        return detail

    async def submit(
        self,
        session: AsyncSession,
        *,
        biz_type: str,
        applicant_employee_id: str,
        title: str,
        payload: dict,
        applicant_user_id: str | None = None,
        biz_ref_id: str | None = None,
    ) -> ApprovalRequest:
        """提交审批申请：员工存在性校验 + handler 载荷校验 + 提交流水留痕。"""
        handler = self._get_handler(biz_type)
        employee = await session.get(Employee, applicant_employee_id)
        if not employee:
            raise NotFoundError(f"员工 {applicant_employee_id} 不存在")
        if employee.status not in _ACTIVE_EMPLOYEE_STATUSES:
            raise ConflictError("仅在职员工可发起审批申请")

        await handler.validate_submit(session, payload)

        request = ApprovalRequest(
            tenant_id=get_tenant_id(),
            biz_type=biz_type,
            biz_ref_id=biz_ref_id,
            applicant_employee_id=applicant_employee_id,
            applicant_user_id=applicant_user_id,
            owner_id=applicant_user_id or employee.user_id,
            title=title,
            payload=payload,
            status="pending",
        )
        session.add(request)
        await session.flush()
        await self._record_action(
            session, request, "submit", actor_id=applicant_user_id
        )
        await self._notify_submit(session, request)
        return request

    async def approve(
        self,
        session: AsyncSession,
        request_id: str,
        *,
        approver_id: str,
        comment: str | None = None,
    ) -> ApprovalRequest:
        """审批通过：handler 应用业务变更（异常回滚保持 pending）+ 流水留痕。"""
        request = await self._get_request(session, request_id)
        if request.status != "pending":
            raise ConflictError(f"审批请求状态为 {request.status}，不可审批")

        handler = self._get_handler(request.biz_type)
        await handler.apply(session, request)

        request.status = "approved"
        request.approver_id = approver_id
        request.approve_comment = comment
        request.approved_at = datetime.now()
        await self._record_action(session, request, "approve", actor_id=approver_id, comment=comment)
        await self._notify_result(session, request, "通过")
        return request

    async def reject(
        self,
        session: AsyncSession,
        request_id: str,
        *,
        approver_id: str,
        comment: str,
    ) -> ApprovalRequest:
        """审批驳回（意见必填）：终态，不触发业务变更。"""
        if not (comment or "").strip():
            raise BadRequestError("驳回须填写审批意见")
        request = await self._get_request(session, request_id)
        if request.status != "pending":
            raise ConflictError(f"审批请求状态为 {request.status}，不可审批")

        request.status = "rejected"
        request.approver_id = approver_id
        request.approve_comment = comment
        request.approved_at = datetime.now()
        await self._record_action(session, request, "reject", actor_id=approver_id, comment=comment)
        await self._notify_result(session, request, "驳回")
        return request

    async def transfer_request(
        self, session: AsyncSession, request_id: str, *, new_owner_id: str
    ) -> ApprovalRequest:
        """移交业务归属人（owner_id 可变归属列；目标须同租户在册）"""
        request = await self._get_request(session, request_id)
        await validate_transfer_target(session, new_owner_id)
        request.owner_id = new_owner_id
        await session.flush()
        return request

    async def cancel(
        self, session: AsyncSession, request_id: str, *, operator_employee_id: str
    ) -> ApprovalRequest:
        """撤销（仅申请人本人待审批单）。"""
        request = await self._get_request(session, request_id)
        if str(request.applicant_employee_id) != str(operator_employee_id):
            raise ConflictError("仅可撤销本人审批申请")
        if request.status != "pending":
            raise ConflictError(f"审批请求状态为 {request.status}，仅待审批可撤销")

        request.status = "cancelled"
        await self._record_action(session, request, "cancel", actor_id=request.applicant_user_id)
        return request

    # ------------------------------------------------------------------ 内部

    async def _notify_submit(
        self, session: AsyncSession, request: ApprovalRequest
    ) -> None:
        """提交通知审批池（具备 hr:approval:approve 权限的租户用户）；失败不阻断。"""
        try:
            recipients = await self._approver_user_ids(session)
            if not recipients:
                return
            from framework.notification.dispatcher import notify

            await notify(
                session=session,
                notification_type="hr_approval_submitted",
                recipients=recipients,
                title="新审批申请待处理",
                content=f"审批申请「{request.title}」已提交，请在审批中心处理。",
                link="/hr/approvals",
            )
        except Exception as exc:  # noqa: BLE001 — 通知失败不阻断审批主流程
            _logger.warning(f"审批提交通知失败 request={request.id}: {exc}")

    async def _notify_result(
        self, session: AsyncSession, request: ApprovalRequest, action_label: str
    ) -> None:
        """通过/驳回通知提交人（含处理意见）；失败不阻断。"""
        if not request.applicant_user_id:
            return
        try:
            from framework.notification.dispatcher import notify

            comment = (request.approve_comment or "").strip()
            content = f"您的申请「{request.title}」已{action_label}。"
            if comment:
                content += f"处理意见：{comment}"
            await notify(
                session=session,
                notification_type=f"hr_approval_{request.status}",
                recipients=[str(request.applicant_user_id)],
                title=f"审批申请已{action_label}",
                content=content,
                link="/hr/self-service",
            )
        except Exception as exc:  # noqa: BLE001 — 通知失败不阻断审批主流程
            _logger.warning(f"审批结果通知失败 request={request.id}: {exc}")

    @staticmethod
    async def _approver_user_ids(session: AsyncSession) -> list[str]:
        """审批池用户：经 iam 角色权限模型反查具备 hr:approval:approve 的用户。"""
        from iam.models.rbac import (
            Permission,
            RolePermission,
            UserRole,
        )

        stmt = (
            select(UserRole.user_id)
            .join(RolePermission, UserRole.role_id == RolePermission.role_id)
            .join(Permission, RolePermission.permission_id == Permission.id)
            .where(
                UserRole.tenant_id == get_tenant_id(),
                Permission.code == "hr:approval:approve",
            )
            .distinct()
        )
        rows = (await session.execute(stmt)).scalars().all()
        return [str(user_id) for user_id in rows]

    @staticmethod
    def _get_handler(biz_type: str) -> Any:
        handler = _HANDLERS.get(biz_type)
        if not handler:
            raise BadRequestError(f"未知审批业务类型: {biz_type}")
        return handler

    async def _get_request(
        self, session: AsyncSession, request_id: str
    ) -> ApprovalRequest:
        request = await session.get(ApprovalRequest, request_id)
        if not request:
            raise NotFoundError(f"审批请求 {request_id} 不存在")
        return request

    async def _record_action(
        self,
        session: AsyncSession,
        request: ApprovalRequest,
        action: str,
        *,
        actor_id: str | None = None,
        comment: str | None = None,
    ) -> None:
        session.add(
            ApprovalAction(
                tenant_id=get_tenant_id(),
                request_id=str(request.id),
                action=action,
                actor_id=actor_id,
                comment=comment,
            )
        )
        await session.flush()

    def to_response(
        self, request: ApprovalRequest, employee: Employee | None = None
    ):
        from hr.schemas.approval import ApprovalRequestResponse

        return ApprovalRequestResponse(
            id=str(request.id),
            biz_type=request.biz_type,
            biz_ref_id=request.biz_ref_id,
            applicant_employee_id=str(request.applicant_employee_id),
            employee_no=employee.employee_no if employee else None,
            employee_name=employee.name if employee else None,
            org_id=str(employee.org_id) if employee and employee.org_id else None,
            applicant_user_id=request.applicant_user_id,
            owner_id=request.owner_id,
            title=request.title,
            payload=request.payload,
            status=request.status,
            approver_id=request.approver_id,
            approve_comment=request.approve_comment,
            approved_at=request.approved_at,
            created_at=request.created_at,
        )


approval_service = ApprovalService()
