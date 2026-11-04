"""薪酬域模型（薪酬项 / 职级薪带 / 员工定薪 / 发薪批次与明细）"""

from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.database import ActiveRecordMixin, TenantMixin

from hr.models import BaseModel


class SalaryItem(BaseModel, TenantMixin, ActiveRecordMixin):
    """
    薪酬项字典（不承载金额）

    code 创建后不可修改（历史数据按 code 关联）；类别清单存租户配置
    SystemSetting hr_salary_setting.categories；被定薪或明细引用后仅可停用。
    """

    __tablename__ = "salary_items"

    code: Mapped[str] = mapped_column(String(64), nullable=False, comment="编码（创建后不可修改）")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="名称")
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="类别：base/performance/bonus/subsidy/deduction（清单租户可扩展）"
    )
    ext_data: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="规则元数据：taxable/social_security_base/monthly_fixed/unit",
    )
    can_edit: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="启用（false=停用）；被引用后只可停用",
    )
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="排序")

    __table_args__ = (
        Index("uq_salary_items_tenant_code", "tenant_id", "code", unique=True),
        {"comment": "薪酬项字典表"},
    )


class SalaryBand(BaseModel, TenantMixin, ActiveRecordMixin):
    """
    职级薪带（版本化）

    effective_to 空 = 当前生效版本；新建版本自动闭合旧区间；
    同职级生效区间不重叠（应用层校验）；历史版本只读，未生效版本可改/删。
    """

    __tablename__ = "salary_bands"

    job_level: Mapped[str] = mapped_column(String(32), nullable=False, comment="职级（P5/M2 等）")
    min_salary: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, comment="带宽下限（元/月）")
    mid_salary: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, comment="中位值（元/月）")
    max_salary: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, comment="带宽上限（元/月）")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, comment="生效起")
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True, comment="生效止（空=当前生效版本）")

    __table_args__ = (
        Index("ix_salary_bands_job_level", "tenant_id", "job_level"),
        {"comment": "职级薪带表"},
    )


class EmployeeSalaryPackage(BaseModel, TenantMixin, ActiveRecordMixin):
    """
    员工定薪（区间版本化）

    同员工同薪酬项生效区间不重叠；调薪事务 = 闭合旧区间 + 生成新区间 +
    写 salary_change 异动流水；离职/调岗按需闭合。
    """

    __tablename__ = "employee_salary_packages"

    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        comment="员工",
    )
    item_id: Mapped[str] = mapped_column(
        ForeignKey("salary_items.id", ondelete="RESTRICT"),
        nullable=False,
        comment="薪酬项",
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, comment="金额（元/月）")
    reason: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="定薪原因：hire/adjust/promotion/perf"
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, comment="生效起（不可早于当日）")
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True, comment="生效止（空=当期生效区间）")

    __table_args__ = (
        Index("ix_salary_packages_employee_id", "employee_id"),
        Index("ix_salary_packages_item_id", "item_id"),
        {"comment": "员工定薪表"},
    )


class PayrollRun(BaseModel, TenantMixin, ActiveRecordMixin):
    """发薪批次；period 租户唯一（重复创建 409）；paid 不可取消。"""

    __tablename__ = "payroll_runs"

    period: Mapped[str] = mapped_column(String(7), nullable=False, comment="期间（YYYY-MM）")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", comment="状态：draft/confirmed/paid/cancelled"
    )
    total_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True, comment="批次总额（试算/修正后回写）")
    employee_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="发放人数（回写）")
    pay_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="发薪日")

    __table_args__ = (
        Index("uq_payroll_runs_tenant_period", "tenant_id", "period", unique=True),
        {"comment": "发薪批次表"},
    )


class PayrollEntry(BaseModel, TenantMixin, ActiveRecordMixin):
    """
    发薪明细

    item_code 为编码快照（历史数据按 code 关联）；performance 类金额 =
    定薪 × 当期绩效系数（一期系数 1.0）；调薪跨区间分段折算；仅 draft 态可修正。
    """

    __tablename__ = "payroll_entries"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("payroll_runs.id", ondelete="CASCADE"),
        nullable=False,
        comment="发薪批次",
    )
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        comment="员工",
    )
    item_id: Mapped[str] = mapped_column(
        ForeignKey("salary_items.id", ondelete="RESTRICT"),
        nullable=False,
        comment="薪酬项",
    )
    item_code: Mapped[str] = mapped_column(String(64), nullable=False, comment="薪酬项编码快照")
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, comment="金额（元）")
    note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注（修正/补发/扣减原因、分段折算留痕）")

    __table_args__ = (
        Index(
            "uq_payroll_entries_tenant_run_emp_code",
            "tenant_id",
            "run_id",
            "employee_id",
            "item_code",
            unique=True,
        ),
        Index("ix_payroll_entries_run_id", "run_id"),
        {"comment": "发薪明细表"},
    )
