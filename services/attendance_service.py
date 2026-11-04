"""考勤服务：记录列表筛选 / 总览统计 / 状态判定 / 同键覆盖写入"""

from datetime import date, datetime, time

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.ctx import get_tenant_id

from hr.models import AttendanceRecord, Employee
from hr.schemas.attendance import (
    AttendanceOrgStat,
    AttendanceRecordResponse,
    AttendanceStatsCards,
    AttendanceStatsResponse,
)
from hr.services.employee_service import employee_service

# 出勤人次口径（缺勤/请假/出差不计入出勤）
_ATTENDANCE_OK_STATUSES = ("normal", "late", "early_leave", "late_early", "missing_card")

# 打卡基准（一期固定班次 09:00-18:00，排班为二期域）
_WORK_START = time(9, 0)
_WORK_END = time(18, 0)


def judge_status(
    check_in_time: datetime | None, check_out_time: datetime | None
) -> str:
    """按打卡时间判定状态：双缺=缺勤 / 单缺=缺卡 / 迟到早退组合。"""
    if check_in_time is None and check_out_time is None:
        return "absent"
    if check_in_time is None or check_out_time is None:
        return "missing_card"
    late = check_in_time.time() > _WORK_START
    early = check_out_time.time() < _WORK_END
    if late and early:
        return "late_early"
    if late:
        return "late"
    if early:
        return "early_leave"
    return "normal"


class AttendanceService:
    """考勤业务（记录由导入通道与请假联动产生，不提供逐条手工维护）"""

    def _base_conditions(
        self,
        *,
        date_from: date | None,
        date_to: date | None,
        keyword: str | None,
    ) -> list:
        conditions = []
        if date_from:
            conditions.append(AttendanceRecord.work_date >= date_from)
        if date_to:
            conditions.append(AttendanceRecord.work_date <= date_to)
        if keyword:
            like = f"%{keyword}%"
            conditions.append(
                or_(Employee.name.ilike(like), Employee.employee_no.ilike(like))
            )
        return conditions

    async def _resolved_conditions(
        self,
        session: AsyncSession,
        *,
        date_from: date | None,
        date_to: date | None,
        org_id: str | None,
        keyword: str | None,
    ) -> list:
        conditions = self._base_conditions(
            date_from=date_from, date_to=date_to, keyword=keyword
        )
        if org_id:
            org_ids = await employee_service.expand_org_ids(session, org_id)
            conditions.append(Employee.org_id.in_(org_ids))
        return conditions

    async def list_records(
        self,
        session: AsyncSession,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        org_id: str | None = None,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        conditions = await self._resolved_conditions(
            session,
            date_from=date_from,
            date_to=date_to,
            org_id=org_id,
            keyword=keyword,
        )
        if status:
            conditions.append(AttendanceRecord.status == status)

        total = (
            await session.execute(
                select(func.count(AttendanceRecord.id))
                .join(Employee, AttendanceRecord.employee_id == Employee.id)
                .where(*conditions)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(AttendanceRecord, Employee)
                .join(Employee, AttendanceRecord.employee_id == Employee.id)
                .where(*conditions)
                .order_by(AttendanceRecord.work_date.desc(), Employee.employee_no)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return {
            "total": total,
            "items": [
                self.to_response(record, employee) for record, employee in rows
            ],
        }

    async def get_stats(
        self,
        session: AsyncSession,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        org_id: str | None = None,
        keyword: str | None = None,
    ) -> AttendanceStatsResponse:
        """统计卡 + 部门聚合（同筛选口径；出勤率=出勤人次/记录总数）。"""
        conditions = await self._resolved_conditions(
            session,
            date_from=date_from,
            date_to=date_to,
            org_id=org_id,
            keyword=keyword,
        )
        join_condition = AttendanceRecord.employee_id == Employee.id

        status_rows = (
            await session.execute(
                select(AttendanceRecord.status, func.count(AttendanceRecord.id))
                .join(Employee, join_condition)
                .where(*conditions)
                .group_by(AttendanceRecord.status)
            )
        ).all()
        cards = self._aggregate_cards(dict(status_rows))

        org_rows = (
            await session.execute(
                select(
                    Employee.org_id,
                    AttendanceRecord.status,
                    func.count(AttendanceRecord.id),
                )
                .join(Employee, join_condition)
                .where(*conditions)
                .group_by(Employee.org_id, AttendanceRecord.status)
            )
        ).all()
        grouped: dict[str, dict[str, int]] = {}
        for org, status_name, count in org_rows:
            grouped.setdefault(str(org) if org else "", {})[status_name] = count
        slices = [
            self._aggregate_org_stat(org_id, counts)
            for org_id, counts in grouped.items()
        ]
        slices.sort(key=lambda item: (-item.attendance_count, item.org_id))
        return AttendanceStatsResponse(cards=cards, org_slices=slices)

    @staticmethod
    def _count_statuses(counts: dict[str, int], statuses: tuple[str, ...]) -> int:
        return sum(counts.get(status, 0) for status in statuses)

    @classmethod
    def _aggregate_cards(cls, counts: dict[str, int]) -> AttendanceStatsCards:
        total = sum(counts.values())
        attendance = cls._count_statuses(counts, _ATTENDANCE_OK_STATUSES)
        rate = round(attendance * 100 / total, 2) if total else None
        return AttendanceStatsCards(
            total_records=total,
            attendance_count=attendance,
            late_count=cls._count_statuses(counts, ("late", "late_early")),
            early_leave_count=cls._count_statuses(
                counts, ("early_leave", "late_early")
            ),
            absent_count=counts.get("absent", 0),
            attendance_rate=rate,
        )

    @classmethod
    def _aggregate_org_stat(
        cls, org_id: str, counts: dict[str, int]
    ) -> AttendanceOrgStat:
        total = sum(counts.values())
        attendance = cls._count_statuses(counts, _ATTENDANCE_OK_STATUSES)
        rate = round(attendance * 100 / total, 2) if total else None
        return AttendanceOrgStat(
            org_id=org_id,
            total_records=total,
            attendance_count=attendance,
            late_count=cls._count_statuses(counts, ("late", "late_early")),
            early_leave_count=cls._count_statuses(
                counts, ("early_leave", "late_early")
            ),
            missing_card_count=counts.get("missing_card", 0),
            absent_count=counts.get("absent", 0),
            attendance_rate=rate,
        )

    async def upsert_record(
        self,
        session: AsyncSession,
        *,
        employee_id: str,
        work_date: date,
        status: str,
        source: str,
        check_in_time: datetime | None = None,
        check_out_time: datetime | None = None,
        overtime_hours: float | None = None,
        remark: str | None = None,
    ) -> tuple[AttendanceRecord, bool]:
        """同键（租户×员工×日期）覆盖写入；返回 (记录, 是否新建)。

        两侧打卡齐则工作时长按时间差计算；导入覆盖与请假联动共用本入口。
        """
        existing = (
            await session.execute(
                select(AttendanceRecord)
                .where(
                    AttendanceRecord.employee_id == employee_id,
                    AttendanceRecord.work_date == work_date,
                )
                .limit(1)
            )
        ).scalar_one_or_none()

        work_hours = None
        if check_in_time and check_out_time:
            seconds = (check_out_time - check_in_time).total_seconds()
            if seconds > 0:
                work_hours = round(seconds / 3600, 2)

        if existing:
            existing.check_in_time = check_in_time
            existing.check_out_time = check_out_time
            existing.work_hours = work_hours
            existing.overtime_hours = overtime_hours
            existing.status = status
            existing.source = source
            existing.remark = remark
            return existing, False

        record = AttendanceRecord(
            tenant_id=get_tenant_id(),
            employee_id=employee_id,
            work_date=work_date,
            check_in_time=check_in_time,
            check_out_time=check_out_time,
            work_hours=work_hours,
            overtime_hours=overtime_hours,
            status=status,
            source=source,
            remark=remark,
        )
        session.add(record)
        return record, True

    def to_response(
        self, record: AttendanceRecord, employee: Employee | None = None
    ) -> AttendanceRecordResponse:
        return AttendanceRecordResponse(
            id=str(record.id),
            employee_id=str(record.employee_id),
            employee_no=employee.employee_no if employee else None,
            employee_name=employee.name if employee else None,
            org_id=str(employee.org_id) if employee and employee.org_id else None,
            work_date=record.work_date,
            check_in_time=record.check_in_time,
            check_out_time=record.check_out_time,
            work_hours=float(record.work_hours) if record.work_hours is not None else None,
            overtime_hours=float(record.overtime_hours)
            if record.overtime_hours is not None
            else None,
            status=record.status,
            source=record.source,
            remark=record.remark,
        )


attendance_service = AttendanceService()
