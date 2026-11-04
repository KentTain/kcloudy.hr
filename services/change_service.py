"""异动服务：入转调离流水留痕 + 离职 iam 联动事件

员工状态与关键字段变更一律经 EmployeeChange 流水（before/after 快照 + 生效日期
+ 操作人），不直接改主档不留痕；离职生效走 Redis Stream 事件驱动账号联动。
"""

from datetime import date
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.ctx import get_user_id
from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError
from framework.events.publisher import event_publisher

from hr.common.events import EmployeeOffboarded
from hr.common.transfer import validate_transfer_target
from hr.models import Employee, EmployeeChange
from hr.schemas.change import ChangeCreate, ChangeResponse

_logger = logger.bind(name=__name__)

# 异动类型 → 允许的前置状态（状态机；类型编码对齐 03.异动管理：
# hire/probate/transfer/level_change/salary_change/offboard）
_CHANGE_ALLOWED_FROM = {
    "probate": ["probation"],
    "transfer": ["probation", "regular", "intern"],
    "level_change": ["probation", "regular", "intern"],
    "salary_change": ["probation", "regular", "intern"],
    "offboard": ["probation", "regular", "intern"],
}


class ChangeService:
    """异动流水与异动发起"""

    async def record_change(
        self,
        session: AsyncSession,
        *,
        employee: Employee,
        change_type: str,
        before_data: dict | None,
        after_data: dict | None,
        effective_date: date,
        operator_id: str | None = None,
    ) -> EmployeeChange:
        """底层写流水（建档/主档维护等自动留痕场景）。"""
        change = EmployeeChange(
            employee_id=employee.id,
            owner_id=employee.user_id,
            change_type=change_type,
            before_data=before_data,
            after_data=after_data,
            effective_date=effective_date,
            operator_id=operator_id or get_user_id(),
        )
        session.add(change)
        await session.flush()
        return change

    async def list_changes(
        self,
        session: AsyncSession,
        *,
        page: int,
        page_size: int,
        employee_id: str | None = None,
        change_type: str | None = None,
        org_id: str | None = None,
        keyword: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> tuple[list[EmployeeChange], int]:
        """异动流水分页检索（跨员工；组织筛选依据快照 after_data.org_id）。"""
        conditions = []
        if employee_id:
            conditions.append(EmployeeChange.employee_id == employee_id)
        if change_type:
            conditions.append(EmployeeChange.change_type == change_type)
        if org_id:
            conditions.append(
                EmployeeChange.after_data["org_id"].astext == org_id
            )
        if start_date:
            conditions.append(EmployeeChange.effective_date >= start_date)
        if end_date:
            conditions.append(EmployeeChange.effective_date <= end_date)
        if keyword:
            employee_ids = await self._find_employee_ids_by_keyword(session, keyword)
            if not employee_ids:
                return [], 0
            conditions.append(EmployeeChange.employee_id.in_(employee_ids))

        total = (
            await session.execute(
                select(func.count(EmployeeChange.id)).where(*conditions)
            )
        ).scalar_one()

        result = await session.execute(
            select(EmployeeChange)
            .where(*conditions)
            .order_by(EmployeeChange.effective_date.desc(), EmployeeChange.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def get_change(self, session: AsyncSession, change_id: str) -> EmployeeChange:
        change = await session.get(EmployeeChange, change_id)
        if not change:
            raise NotFoundError(f"异动流水 {change_id} 不存在")
        return change

    async def transfer_change(
        self, session: AsyncSession, change_id: str, *, new_owner_id: str
    ) -> EmployeeChange:
        """移交业务归属人（owner_id 可变归属列；目标须同租户在册）"""
        change = await self.get_change(session, change_id)
        await validate_transfer_target(session, new_owner_id)
        change.owner_id = new_owner_id
        await session.flush()
        return change

    async def submit_change(
        self, session: AsyncSession, employee_id: str, data: ChangeCreate
    ) -> ChangeResponse:
        """发起异动（转正/调岗/调薪/离职）：校验状态机 → 更新主档 → 写流水。

        离职提交后发布联动事件（生效日由 listeners 消费：iam 停用账号 + 移出组织
        + 站内信回告），事件失败不阻塞异动主流程。
        """
        employee = await session.get(Employee, employee_id)
        if not employee:
            raise NotFoundError(f"员工 {employee_id} 不存在")

        if data.effective_date < date.today():
            raise BadRequestError("生效日期不可早于当前日期")

        allowed = _CHANGE_ALLOWED_FROM.get(data.change_type)
        if allowed is None:
            raise BadRequestError(f"不支持的异动类型: {data.change_type}")
        if employee.status not in allowed:
            raise ConflictError(
                f"当前状态 {employee.status} 不允许发起 {data.change_type} 异动"
            )

        before = self._snapshot(employee)
        after = dict(before)

        if data.change_type == "probate":
            employee.status = "regular"
            employee.regular_date = data.effective_date
        elif data.change_type == "transfer":
            if data.org_id is None and data.position_id is None:
                raise BadRequestError("调岗异动须提供新组织/新岗位至少一项")
            if data.org_id is not None:
                employee.org_id = data.org_id
            if data.position_id is not None:
                employee.position_id = data.position_id
        elif data.change_type == "level_change":
            if data.job_level is None:
                raise BadRequestError("职级变更须提供新职级")
            employee.job_level = data.job_level
        elif data.change_type == "salary_change":
            # 薪酬方案快照随流水落 after_data；定薪区间闭合随薪酬域（阶段 4）接入
            if not data.salary_items:
                raise BadRequestError("调薪异动须提供薪酬方案明细")
        elif data.change_type == "offboard":
            employee.status = "offboarded"
            employee.offboard_date = data.effective_date

        after = self._snapshot(employee)
        after_data: dict[str, Any] = dict(after)
        if data.change_type == "probate" and data.remark:
            after_data["remark"] = data.remark
        if data.change_type == "offboard":
            after_data["offboard_reason"] = data.reason
            if data.remark:
                after_data["remark"] = data.remark
        if data.change_type == "salary_change":
            after_data["salary_items"] = data.salary_items

        change = await self.record_change(
            session,
            employee=employee,
            change_type=data.change_type,
            before_data=before,
            after_data=after_data,
            effective_date=data.effective_date,
        )

        if data.change_type == "offboard":
            await self._publish_offboard_event(
                session, employee, data, operator_id=change.operator_id
            )

        _logger.info(
            f"异动提交完成: {employee.employee_no} {data.change_type} 生效日 {data.effective_date}"
        )
        return ChangeResponse.model_validate(change)

    # ── 内部工具 ──

    async def _publish_offboard_event(
        self,
        session: AsyncSession,
        employee: Employee,
        data: ChangeCreate,
        *,
        operator_id: str | None,
    ) -> None:
        """离职生效事件（事务内发布：提交后发布、回滚丢弃）。"""
        await event_publisher.publish(
            EmployeeOffboarded(
                tenant_id=employee.tenant_id,
                employee_id=employee.id,
                employee_no=employee.employee_no,
                employee_name=employee.name,
                user_id=employee.user_id,
                org_id=employee.org_id,
                offboard_date=str(data.effective_date),
                operator_id=operator_id,
            ),
            session=session,
        )

    async def _find_employee_ids_by_keyword(
        self, session: AsyncSession, keyword: str
    ) -> list[str]:
        from sqlalchemy import or_

        like = f"%{keyword}%"
        result = await session.execute(
            select(Employee.id).where(
                or_(Employee.employee_no.ilike(like), Employee.name.ilike(like))
            )
        )
        return [row[0] for row in result.all()]

    @staticmethod
    def _snapshot(employee: Employee) -> dict:
        return {
            "name": employee.name,
            "org_id": employee.org_id,
            "position_id": employee.position_id,
            "job_level": employee.job_level,
            "status": employee.status,
        }


change_service = ChangeService()
