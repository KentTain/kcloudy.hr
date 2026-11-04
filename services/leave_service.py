"""假期服务：类型字典（删除保护）+ 假期余额（年度惰性初始化 / 调整审计）"""

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.clients.iam_client import get_iam_client
from framework.common.ctx import get_tenant_id
from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError

from hr.models import Employee, LeaveBalance, LeaveRequest, LeaveType

_ACTIVE_EMPLOYEE_STATUSES = ("probation", "regular", "intern")


class LeaveService:
    """假期类型与余额业务（余额=总额度−已用−冻结，计算值不落列）"""

    # ── 假期类型 ──

    async def list_types(
        self,
        session: AsyncSession,
        *,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        conditions = []
        if status:
            conditions.append(LeaveType.status == status)
        total = (
            await session.execute(
                select(func.count(LeaveType.id)).where(*conditions)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(LeaveType)
                .where(*conditions)
                .order_by(LeaveType.code)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return {
            "total": total,
            "items": [self.to_type_response(item) for item in rows],
        }

    async def list_enabled_types(self, session: AsyncSession) -> list[LeaveType]:
        return list(
            (
                await session.execute(
                    select(LeaveType).where(LeaveType.status == "enabled").order_by(LeaveType.code)
                )
            ).scalars().all()
        )

    async def create_type(
        self, session: AsyncSession, data  # LeaveTypeCreate
    ) -> LeaveType:
        if data.unit not in ("day", "hour"):
            raise BadRequestError("计量单位须为 day/hour")
        if data.quota_rule not in ("annual_fixed", "manual"):
            raise BadRequestError("额度规则须为 annual_fixed/manual")
        existing = (
            await session.execute(
                select(LeaveType.id).where(LeaveType.code == data.code).limit(1)
            )
        ).scalar_one_or_none()
        if existing:
            raise ConflictError(f"假期类型编码 {data.code} 已存在")
        leave_type = LeaveType(
            tenant_id=get_tenant_id(),
            code=data.code,
            name=data.name,
            unit=data.unit,
            paid=data.paid,
            quota_rule=data.quota_rule,
            default_quota=data.default_quota,
            status="enabled",
        )
        session.add(leave_type)
        await session.flush()
        return leave_type

    async def get_type(self, session: AsyncSession, type_id: str) -> LeaveType:
        leave_type = await session.get(LeaveType, type_id)
        if not leave_type:
            raise NotFoundError(f"假期类型 {type_id} 不存在")
        return leave_type

    async def update_type(
        self, session: AsyncSession, type_id: str, data  # LeaveTypeUpdate
    ) -> LeaveType:
        leave_type = await self.get_type(session, type_id)
        updates = data.model_dump(exclude_unset=True, exclude_none=True)
        if "status" in updates and updates["status"] not in ("enabled", "disabled"):
            raise BadRequestError("状态须为 enabled/disabled")
        if "unit" in updates and updates["unit"] not in ("day", "hour"):
            raise BadRequestError("计量单位须为 day/hour")
        for field, value in updates.items():
            setattr(leave_type, field, value)
        return leave_type

    async def delete_type(self, session: AsyncSession, type_id: str) -> None:
        """删除保护：被余额或请假单引用的类型仅可停用。"""
        leave_type = await self.get_type(session, type_id)
        balance_ref = (
            await session.execute(
                select(LeaveBalance.id)
                .where(LeaveBalance.leave_type_id == type_id)
                .limit(1)
            )
        ).scalar_one_or_none()
        request_ref = (
            await session.execute(
                select(LeaveRequest.id)
                .where(LeaveRequest.leave_type_id == type_id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if balance_ref or request_ref:
            raise ConflictError(f"假期类型 {leave_type.code} 已被引用，只可停用")
        await session.delete(leave_type)

    # ── 假期余额 ──

    async def list_balances(
        self,
        session: AsyncSession,
        *,
        year: int | None = None,
        org_id: str | None = None,
        keyword: str | None = None,
        leave_type_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        year = year or date.today().year
        await self._ensure_year_balances(session, year)

        conditions = [LeaveBalance.year == year]
        if org_id:
            from hr.services.employee_service import employee_service

            org_ids = await employee_service.expand_org_ids(session, org_id)
            conditions.append(Employee.org_id.in_(org_ids))
        if keyword:
            like = f"%{keyword}%"
            conditions.append(
                or_(Employee.name.ilike(like), Employee.employee_no.ilike(like))
            )
        if leave_type_id:
            conditions.append(LeaveBalance.leave_type_id == leave_type_id)

        total = (
            await session.execute(
                select(func.count(LeaveBalance.id))
                .join(Employee, LeaveBalance.employee_id == Employee.id)
                .where(*conditions)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(LeaveBalance, Employee, LeaveType)
                .join(Employee, LeaveBalance.employee_id == Employee.id)
                .join(LeaveType, LeaveBalance.leave_type_id == LeaveType.id)
                .where(*conditions)
                .order_by(Employee.employee_no, LeaveType.code)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return {
            "total": total,
            "items": [
                self.to_balance_response(balance, employee, leave_type)
                for balance, employee, leave_type in rows
            ],
        }

    async def get_or_create_balance(
        self,
        session: AsyncSession,
        employee_id: str,
        leave_type: LeaveType,
        year: int,
    ) -> LeaveBalance:
        """单点余额获取（缺失按额度规则初始化：manual/无默认额度 → 0）。"""
        balance = (
            await session.execute(
                select(LeaveBalance)
                .where(
                    LeaveBalance.employee_id == employee_id,
                    LeaveBalance.leave_type_id == leave_type.id,
                    LeaveBalance.year == year,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if balance:
            return balance
        initial = (
            float(leave_type.default_quota)
            if leave_type.quota_rule == "annual_fixed" and leave_type.default_quota
            else 0.0
        )
        balance = LeaveBalance(
            tenant_id=get_tenant_id(),
            employee_id=employee_id,
            leave_type_id=leave_type.id,
            year=year,
            total_quota=initial,
        )
        session.add(balance)
        await session.flush()
        return balance

    async def adjust_balance(
        self,
        session: AsyncSession,
        balance_id: str,
        total_quota: float,
        *,
        operator_id: str,
    ) -> LeaveBalance:
        """调整年度总额度（写审计：前后快照 + 操作人）。"""
        balance = await session.get(LeaveBalance, balance_id)
        if not balance:
            raise NotFoundError(f"假期余额 {balance_id} 不存在")
        if total_quota < 0:
            raise BadRequestError("总额度不可为负")
        if float(balance.frozen) > total_quota:
            raise BadRequestError("总额度不可低于当前冻结额度")
        before = {
            "total_quota": float(balance.total_quota),
            "used": float(balance.used),
            "frozen": float(balance.frozen),
        }
        balance.total_quota = total_quota
        await get_iam_client().create_audit_log(
            session,
            business_domain="hr",
            operation_type="adjust",
            resource_type="leave_balance",
            resource_name=f"假期余额 {balance.employee_id} {balance.year}",
            resource_id=str(balance.id),
            detail={
                "operator_id": operator_id,
                "before": before,
                "after": {"total_quota": total_quota},
            },
        )
        return balance

    async def _ensure_year_balances(self, session: AsyncSession, year: int) -> None:
        """年度余额惰性初始化：在职员工 × 启用类型缺失行按默认额度补建。"""
        employees = (
            await session.execute(
                select(Employee.id, Employee.employee_no).where(
                    Employee.status.in_(_ACTIVE_EMPLOYEE_STATUSES)
                )
            )
        ).all()
        leave_types = await self.list_enabled_types(session)
        if not employees or not leave_types:
            return

        existing = (
            await session.execute(
                select(LeaveBalance.employee_id, LeaveBalance.leave_type_id).where(
                    LeaveBalance.year == year
                )
            )
        ).all()
        existing_keys = {
            (str(employee_id), str(type_id)) for employee_id, type_id in existing
        }
        for employee_id, _employee_no in employees:
            for leave_type in leave_types:
                key = (str(employee_id), str(leave_type.id))
                if key in existing_keys:
                    continue
                initial = (
                    float(leave_type.default_quota)
                    if leave_type.quota_rule == "annual_fixed"
                    and leave_type.default_quota
                    else 0.0
                )
                session.add(
                    LeaveBalance(
                        tenant_id=get_tenant_id(),
                        employee_id=str(employee_id),
                        leave_type_id=str(leave_type.id),
                        year=year,
                        total_quota=initial,
                    )
                )
        await session.flush()

    # ── 响应构造 ──

    def to_type_response(self, leave_type: LeaveType):
        from hr.schemas.leave import LeaveTypeResponse

        return LeaveTypeResponse(
            id=str(leave_type.id),
            code=leave_type.code,
            name=leave_type.name,
            unit=leave_type.unit,
            paid=leave_type.paid,
            quota_rule=leave_type.quota_rule,
            default_quota=float(leave_type.default_quota)
            if leave_type.default_quota is not None
            else None,
            status=leave_type.status,
        )

    def to_balance_response(
        self, balance: LeaveBalance, employee: Employee, leave_type: LeaveType
    ):
        from hr.schemas.leave import LeaveBalanceResponse

        total = float(balance.total_quota)
        used = float(balance.used)
        frozen = float(balance.frozen)
        return LeaveBalanceResponse(
            id=str(balance.id),
            employee_id=str(balance.employee_id),
            employee_no=employee.employee_no if employee else None,
            employee_name=employee.name if employee else None,
            org_id=str(employee.org_id) if employee and employee.org_id else None,
            leave_type_id=str(balance.leave_type_id),
            leave_type_code=leave_type.code if leave_type else None,
            leave_type_name=leave_type.name if leave_type else None,
            unit=leave_type.unit if leave_type else None,
            year=balance.year,
            total_quota=total,
            used=used,
            frozen=frozen,
            balance=round(total - used - frozen, 2),
        )


leave_service = LeaveService()
