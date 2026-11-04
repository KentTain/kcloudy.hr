"""绩效域模型（考核周期 / 绩效目标 / 绩效评估）"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from framework.database import ActiveRecordMixin, SoftDeleteMixin, TenantMixin

from hr.models import BaseModel


class PerfCycle(BaseModel, TenantMixin, ActiveRecordMixin, SoftDeleteMixin):
    """
    考核周期

    状态机单向推进 draft → active → scoring → calibrating → closed；
    仅 draft 可编辑/删除；closed 后评级与系数只读（发薪试算消费）。
    """

    __tablename__ = "perf_cycles"

    name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="周期名（如 2026-H1，租户唯一）"
    )
    start_date: Mapped[date] = mapped_column(nullable=False, comment="起始日期")
    end_date: Mapped[date] = mapped_column(nullable=False, comment="截止日期")
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        comment="状态：draft/active/scoring/calibrating/closed",
    )

    __table_args__ = (
        Index("uq_perf_cycles_tenant_name", "tenant_id", "name", unique=True),
        {"comment": "考核周期表"},
    )


class PerfGoal(BaseModel, TenantMixin, ActiveRecordMixin):
    """
    绩效目标（员工 × 周期）

    code 租户唯一（建议带员工/周期维度）；weight 为百分数权重，
    同员工同周期合计须为 100（整批提交时校验，单目标编辑复核）；
    progress 达 100 自动置 completed。
    """

    __tablename__ = "perf_goals"

    cycle_id: Mapped[str] = mapped_column(
        ForeignKey("perf_cycles.id", ondelete="CASCADE"),
        nullable=False,
        comment="考核周期",
    )
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        comment="负责人（员工）",
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False, comment="目标编码（创建后不可修改）")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="目标名称")
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, comment="权重（百分数，周期内合计 100）")
    target_value: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="目标值描述"
    )
    actual_value: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="实际值描述"
    )
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="进度（0-100）")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", comment="状态：open/completed"
    )

    __table_args__ = (
        Index("uq_perf_goals_tenant_code", "tenant_id", "code", unique=True),
        Index("ix_perf_goals_tenant_cycle", "tenant_id", "cycle_id"),
        Index("ix_perf_goals_tenant_employee", "tenant_id", "employee_id"),
        {"comment": "绩效目标表"},
    )


class PerfReview(BaseModel, TenantMixin, ActiveRecordMixin):
    """
    绩效评估（被评人 × 周期唯一）

    pending（发起）→ submitted（评分：self_score 自评 + score 上级评分 + rating 初评）
    → calibrated（校准：calibrated_rating/意见/操作人/时间留痕）；
    周期收口时按 calibrated_rating 优先回退 rating 映射写 coefficient（缺省 1.0）。
    """

    __tablename__ = "perf_reviews"

    cycle_id: Mapped[str] = mapped_column(
        ForeignKey("perf_cycles.id", ondelete="CASCADE"),
        nullable=False,
        comment="考核周期",
    )
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        comment="被评人（员工）",
    )
    reviewer_employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        comment="评估人（员工，通常直属上级）",
    )
    self_score: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True, comment="自评分"
    )
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True, comment="上级评分")
    rating: Mapped[str | None] = mapped_column(
        String(2), nullable=True, comment="初评评级（S/A/B/C/D，评分时填写）"
    )
    calibrated_rating: Mapped[str | None] = mapped_column(
        String(2), nullable=True, comment="校准后评级（S/A/B/C/D）"
    )
    calibrated_by_user_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, comment="校准操作人（弱引用 iam 用户）"
    )
    calibration_comment: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="校准意见（校准必填）"
    )
    calibrated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="校准时间"
    )
    coefficient: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True, comment="绩效系数（周期收口时按评级映射写入，兜底 1.0）"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", comment="状态：pending/submitted/calibrated"
    )

    __table_args__ = (
        Index(
            "uq_perf_reviews_tenant_cycle_emp",
            "tenant_id",
            "cycle_id",
            "employee_id",
            unique=True,
        ),
        Index("ix_perf_reviews_tenant_cycle", "tenant_id", "cycle_id"),
        Index("ix_perf_reviews_tenant_reviewer", "tenant_id", "reviewer_employee_id", "status"),
        {"comment": "绩效评估表"},
    )
