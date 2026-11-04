"""考勤假勤域模型：考勤记录 / 导入批次 / 假期类型 / 假期余额 / 请假单"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.database import ActiveRecordMixin, OwnerMixin, SoftDeleteMixin, TenantMixin

from hr.models import BaseModel


class AttendanceRecord(BaseModel, TenantMixin, ActiveRecordMixin):
    """
    考勤记录（只读列表，不提供逐条增删改）

    同键重复导入覆盖更新；status 由系统按打卡时间与规则判定；
    请假审批通过自动写入（status=leave，source=leave，同键覆盖语义）。
    """

    __tablename__ = "attendance_records"

    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        comment="员工",
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False, comment="考勤日期")
    check_in_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="上班打卡时间")
    check_out_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="下班打卡时间")
    work_hours: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True, comment="工作时长（小时）")
    overtime_hours: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True, comment="加班时长（小时）")
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="状态：normal/late/early_leave/late_early/absent/missing_card/leave/trip",
    )
    source: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="来源：excel/ai/leave"
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    __table_args__ = (
        Index("uq_attendance_records_tenant_emp_date", "tenant_id", "employee_id", "work_date", unique=True),
        Index("ix_attendance_records_work_date", "tenant_id", "work_date"),
        Index("ix_attendance_records_status", "tenant_id", "status"),
        {"comment": "考勤记录表"},
    )


class AttendanceImportBatch(BaseModel, TenantMixin, ActiveRecordMixin):
    """
    考勤导入批次（Excel / AI 双通道）

    file_key 为原文档临时区位置（临时桶，7 天自动清理，导入完成后清理）；
    row_results 承载行级校验明细；完成时回写新增/覆盖/丢弃/失败计数。
    """

    __tablename__ = "attendance_import_batches"

    channel: Mapped[str] = mapped_column(String(10), nullable=False, comment="导入通道：excel/ai")
    file_key: Mapped[str] = mapped_column(String(512), nullable=False, comment="原文档临时区位置（临时桶）")
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        comment="状态：pending/parsing/parsed/completed/failed",
    )
    field_mapping: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="识别表头 ↔ 标准字段映射（AI 通道）"
    )
    row_results: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, comment="行级校验明细（行号/可解析/未匹配员工/字段缺失/错误原因/勾选状态）"
    )
    new_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="新增条数"
    )
    overwrite_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="覆盖条数"
    )
    discard_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="丢弃条数（AI 未勾选行）"
    )
    fail_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="失败条数（Excel dryRun 失败行）"
    )
    operator_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="操作人（弱引用 iam 用户）")

    __table_args__ = (
        {"comment": "考勤导入批次表"},
    )


class LeaveType(BaseModel, TenantMixin, ActiveRecordMixin, SoftDeleteMixin):
    """
    假期类型

    code 创建后不可修改；被余额或请假单引用仅可停用不可删；
    停用后不可新发起，存量不受影响；quota_rule=manual 的类型新年度余额初始化为 0。
    """

    __tablename__ = "leave_types"

    code: Mapped[str] = mapped_column(String(32), nullable=False, comment="编码（创建后不可修改）")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="名称")
    unit: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="计量单位：day/hour（决定时长计算与展示口径）"
    )
    paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否带薪")
    quota_rule: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="额度规则：annual_fixed按年度固定额度/manual仅手工调整"
    )
    default_quota: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True, comment="默认年度额度（新年度初始化余额带入；单位随 unit）"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="enabled", comment="状态：enabled/disabled"
    )

    __table_args__ = (
        Index("uq_leave_types_tenant_code", "tenant_id", "code", unique=True),
        {"comment": "假期类型表"},
    )


class LeaveBalance(BaseModel, TenantMixin, ActiveRecordMixin):
    """
    假期余额（员工 × 类型 × 年度）

    余额 = total_quota − used − frozen（计算值不落列）；
    新年度惰性初始化；额度调整写审计。
    """

    __tablename__ = "leave_balances"

    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        comment="员工",
    )
    leave_type_id: Mapped[str] = mapped_column(
        ForeignKey("leave_types.id", ondelete="RESTRICT"),
        nullable=False,
        comment="假期类型",
    )
    year: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="年度"
    )
    total_quota: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, comment="总额度")
    used: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0, comment="已用")
    frozen: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0, comment="冻结（提交时冻结，驳回/撤销释放）")

    __table_args__ = (
        Index(
            "uq_leave_balances_tenant_emp_type_year",
            "tenant_id",
            "employee_id",
            "leave_type_id",
            "year",
            unique=True,
        ),
        Index("ix_leave_balances_employee_id", "employee_id"),
        {"comment": "假期余额表"},
    )


class LeaveRequest(BaseModel, TenantMixin, ActiveRecordMixin, OwnerMixin):
    """
    请假单

    duration 系统计算只读（天=闭区间天数 / 小时=时间差跨天截断）；
    须同一年度内、与本人待审批/已通过单不重叠；
    通过 → 冻结转已用 + 写考勤记录；驳回/撤销 → 释放冻结；驳回时审批意见必填。
    """

    __tablename__ = "leave_requests"

    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        comment="员工",
    )
    leave_type_id: Mapped[str] = mapped_column(
        ForeignKey("leave_types.id", ondelete="RESTRICT"),
        nullable=False,
        comment="假期类型",
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="起始时间")
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="结束时间")
    duration: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, comment="时长（系统计算，单位随类型）")
    reason: Mapped[str] = mapped_column(Text, nullable=False, comment="事由")
    attachment_file: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="证明材料（common/upload 通道，可选）"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", comment="状态：pending/approved/rejected/cancelled"
    )
    approver_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, comment="审批人（hr:leave:approve 权限人，弱引用 iam 用户）"
    )
    approve_comment: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="审批意见（驳回必填）")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="审批时间")

    __table_args__ = (
        Index("ix_leave_requests_employee_id", "employee_id"),
        Index("ix_leave_requests_status", "tenant_id", "status"),
        Index("ix_leave_requests_approver", "tenant_id", "approver_id", "status"),
        {"comment": "请假单表"},
    )
