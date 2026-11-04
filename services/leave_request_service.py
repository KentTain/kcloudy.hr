"""请假服务：提交校验（余额/重叠/年度）+ 审批状态机 + 余额联动 + 考勤回写

状态机：pending → approved（冻结转已用 + 逐日写考勤 leave）/ rejected（意见必填，
释放冻结）/ cancelled（本人撤销待审批单，释放冻结）。
"""

from datetime import date, datetime

from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.ctx import get_tenant_id
from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError
from framework.database import skip_owner_filter

from hr.common.transfer import validate_transfer_target

from hr.models import (
    AttendanceRecord,
    Employee,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
)
from hr.services.attendance_service import attendance_service
from hr.services.employee_service import employee_service
from hr.services.leave_service import leave_service

_logger = logger.bind(name=__name__)

_ACTIVE_EMPLOYEE_STATUSES = ("probation", "regular", "intern")


def calculate_duration(unit: str, start_time: datetime, end_time: datetime) -> float:
    """时长系统计算只读：天=起止日期闭区间天数；小时=时间差（2 位小数）。"""
    if unit == "day":
        return float((end_time.date() - start_time.date()).days + 1)
    return round((end_time - start_time).total_seconds() / 3600, 2)


class LeaveRequestService:
    """请假单业务（审批动作需 hr:leave:approve；驳回意见必填）"""

    async def list_requests(
        self,
        session: AsyncSession,
        *,
        status: str | None = None,
        leave_type_id: str | None = None,
        org_id: str | None = None,
        keyword: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        employee_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        conditions = []
        if status:
            conditions.append(LeaveRequest.status == status)
        if leave_type_id:
            conditions.append(LeaveRequest.leave_type_id == leave_type_id)
        if employee_id:
            conditions.append(LeaveRequest.employee_id == employee_id)
        if org_id:
            org_ids = await employee_service.expand_org_ids(session, org_id)
            conditions.append(Employee.org_id.in_(org_ids))
        if keyword:
            like = f"%{keyword}%"
            conditions.append(
                or_(Employee.name.ilike(like), Employee.employee_no.ilike(like))
            )
        if date_from:
            conditions.append(LeaveRequest.start_time >= datetime.combine(date_from, datetime.min.time()))
        if date_to:
            conditions.append(LeaveRequest.start_time < datetime.combine(date_to, datetime.min.time()).replace(hour=23, minute=59, second=59))

        total = (
            await session.execute(
                select(func.count(LeaveRequest.id))
                .join(Employee, LeaveRequest.employee_id == Employee.id)
                .where(*conditions)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(LeaveRequest, Employee, LeaveType)
                .join(Employee, LeaveRequest.employee_id == Employee.id)
                .join(LeaveType, LeaveRequest.leave_type_id == LeaveType.id)
                .where(*conditions)
                .order_by(LeaveRequest.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return {
            "total": total,
            "items": [
                self.to_response(request, employee, leave_type)
                for request, employee, leave_type in rows
            ],
        }

    async def submit_request(
        self,
        session: AsyncSession,
        employee_id: str,
        data,  # LeaveRequestCreate
    ) -> LeaveRequest:
        """提交请假申请：校验通过后冻结对应额度。"""
        employee = await session.get(Employee, employee_id)
        if not employee:
            raise NotFoundError(f"员工 {employee_id} 不存在")
        if employee.status not in _ACTIVE_EMPLOYEE_STATUSES:
            raise ConflictError("仅在职员工可发起请假申请")
        if data.end_time <= data.start_time:
            raise BadRequestError("结束时间须晚于起始时间")
        if data.start_time.year != data.end_time.year:
            raise BadRequestError("请假起止须在同一余额年度内")

        leave_type = await session.get(LeaveType, data.leave_type_id)
        if not leave_type:
            raise NotFoundError(f"假期类型 {data.leave_type_id} 不存在")
        if leave_type.status != "enabled":
            raise BadRequestError(f"假期类型 {leave_type.name} 已停用，不可发起申请")

        duration = calculate_duration(leave_type.unit, data.start_time, data.end_time)
        if duration <= 0:
            raise BadRequestError("请假时长须大于 0")

        # 重叠校验属完整性检查（目标员工的既有单），不受操作人数据范围裁剪
        with skip_owner_filter():
            overlap = (
                await session.execute(
                    select(LeaveRequest.id)
                    .where(
                        LeaveRequest.employee_id == employee_id,
                        LeaveRequest.status.in_(("pending", "approved")),
                        LeaveRequest.start_time < data.end_time,
                        LeaveRequest.end_time > data.start_time,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
        if overlap:
            raise ConflictError("请假区间与本人待审批/已通过请假单重叠")

        balance = await leave_service.get_or_create_balance(
            session, employee_id, leave_type, data.start_time.year
        )
        available = float(balance.total_quota) - float(balance.used) - float(balance.frozen)
        if duration > available:
            raise BadRequestError(
                f"假期余额不足：可用 {available}，需 {duration}（单位 {leave_type.unit}）"
            )

        balance.frozen = float(balance.frozen) + duration
        request = LeaveRequest(
            tenant_id=get_tenant_id(),
            employee_id=employee_id,
            owner_id=employee.user_id,
            leave_type_id=leave_type.id,
            start_time=data.start_time,
            end_time=data.end_time,
            duration=duration,
            reason=data.reason,
            attachment_file=data.attachment_file,
            status="pending",
        )
        session.add(request)
        await session.flush()
        return request

    async def cancel_request(
        self, session: AsyncSession, request_id: str, operator_employee_id: str
    ) -> LeaveRequest:
        """撤销（仅本人待审批单）：释放冻结额度。"""
        request = await self._get_request(session, request_id)
        if str(request.employee_id) != str(operator_employee_id):
            raise ConflictError("仅可撤销本人请假单")
        if request.status != "pending":
            raise ConflictError(f"请假单状态为 {request.status}，仅待审批可撤销")
        await self._release_frozen(session, request)
        request.status = "cancelled"
        return request

    async def approve(
        self,
        session: AsyncSession,
        request_id: str,
        *,
        approver_id: str,
        comment: str | None = None,
    ) -> LeaveRequest:
        """审批通过：冻结转已用 + 按请假区间逐日写考勤（status=leave）。"""
        request = await self._get_request(session, request_id)
        if request.status != "pending":
            raise ConflictError(f"请假单状态为 {request.status}，不可审批")
        balance = await self._get_balance(session, request)
        if float(balance.frozen) < float(request.duration):
            raise ConflictError("冻结额度已被并发调整，请驳回后由员工重新提交")

        leave_type = await session.get(LeaveType, request.leave_type_id)
        balance.frozen = float(balance.frozen) - float(request.duration)
        balance.used = float(balance.used) + float(request.duration)
        request.status = "approved"
        request.approver_id = approver_id
        request.approve_comment = comment
        request.approved_at = datetime.now()

        await self._write_attendance(session, request, leave_type)
        await session.flush()
        _logger.info(
            f"请假审批通过 request={request_id} employee={request.employee_id} "
            f"duration={request.duration}"
        )
        return request

    async def reject(
        self,
        session: AsyncSession,
        request_id: str,
        *,
        approver_id: str,
        comment: str,
    ) -> LeaveRequest:
        """审批驳回（意见必填）：释放冻结额度。"""
        if not (comment or "").strip():
            raise BadRequestError("驳回须填写审批意见")
        request = await self._get_request(session, request_id)
        if request.status != "pending":
            raise ConflictError(f"请假单状态为 {request.status}，不可审批")
        await self._release_frozen(session, request)
        request.status = "rejected"
        request.approver_id = approver_id
        request.approve_comment = comment
        request.approved_at = datetime.now()
        return request

    async def transfer(
        self, session: AsyncSession, request_id: str, *, new_owner_id: str
    ) -> LeaveRequest:
        """移交业务归属人（owner_id 可变归属列；目标须同租户在册）"""
        request = await self._get_request(session, request_id)
        await validate_transfer_target(session, new_owner_id)
        request.owner_id = new_owner_id
        await session.flush()
        return request

    # ------------------------------------------------------------------ 内部

    async def _get_request(
        self, session: AsyncSession, request_id: str
    ) -> LeaveRequest:
        request = await session.get(LeaveRequest, request_id)
        if not request:
            raise NotFoundError(f"请假单 {request_id} 不存在")
        return request

    async def _get_balance(
        self, session: AsyncSession, request: LeaveRequest
    ) -> LeaveBalance:
        balance = (
            await session.execute(
                select(LeaveBalance)
                .where(
                    LeaveBalance.employee_id == request.employee_id,
                    LeaveBalance.leave_type_id == request.leave_type_id,
                    LeaveBalance.year == request.start_time.year,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if not balance:
            raise ConflictError("假期余额行不存在，无法完成审批")
        return balance

    async def _release_frozen(
        self, session: AsyncSession, request: LeaveRequest
    ) -> None:
        balance = await self._get_balance(session, request)
        balance.frozen = float(balance.frozen) - float(request.duration)

    async def _write_attendance(
        self,
        session: AsyncSession,
        request: LeaveRequest,
        leave_type: LeaveType,
    ) -> None:
        remark = f"请假：{leave_type.name}"
        current = request.start_time.date()
        end_date = request.end_time.date()
        while current <= end_date:
            await attendance_service.upsert_record(
                session,
                employee_id=str(request.employee_id),
                work_date=current,
                status="leave",
                source="leave",
                remark=remark,
            )
            current = date.fromordinal(current.toordinal() + 1)

    def to_response(
        self,
        request: LeaveRequest,
        employee: Employee | None = None,
        leave_type: LeaveType | None = None,
    ):
        from hr.schemas.leave import LeaveRequestResponse

        return LeaveRequestResponse(
            id=str(request.id),
            employee_id=str(request.employee_id),
            employee_no=employee.employee_no if employee else None,
            employee_name=employee.name if employee else None,
            org_id=str(employee.org_id) if employee and employee.org_id else None,
            owner_id=request.owner_id,
            leave_type_id=str(request.leave_type_id),
            leave_type_code=leave_type.code if leave_type else None,
            leave_type_name=leave_type.name if leave_type else None,
            unit=leave_type.unit if leave_type else None,
            start_time=request.start_time,
            end_time=request.end_time,
            duration=float(request.duration),
            reason=request.reason,
            attachment_file=request.attachment_file,
            status=request.status,
            approver_id=request.approver_id,
            approve_comment=request.approve_comment,
            approved_at=request.approved_at,
            created_at=request.created_at,
        )


leave_request_service = LeaveRequestService()
