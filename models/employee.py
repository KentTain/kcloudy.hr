"""人事域模型：员工主档 / EAV 属性 / 合同 / 附件 / 岗位 / 异动流水"""

from datetime import date

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.database import ActiveRecordMixin, OwnerMixin, SoftDeleteMixin, TenantMixin

from hr.models import BaseModel


class Employee(BaseModel, TenantMixin, ActiveRecordMixin, SoftDeleteMixin):
    """
    员工主档

    id_card_enc/bank_card_enc 为列级加密密文（AES-GCM，密钥走平台 KMS 配置），
    无 hr:employee:sensitive 权限回掩码；org_id/user_id 为跨模块弱引用无外键，
    user_id 租户内与 iam 用户一对一（开通账号后回填）。
    """

    __tablename__ = "employees"

    employee_no: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="工号，建档自动生成，租户内唯一"
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="姓名")
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="性别")
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="出生日期")
    id_card_enc: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="证件号密文（列级加密）")
    bank_card_enc: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="银行卡号密文（列级加密）")
    bank_name: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="开户行（代发导出用，非敏感明文）")
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="手机号")
    work_email: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="工作邮箱")
    org_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, comment="所属组织（弱引用 iam.organizations，无外键）"
    )
    position_id: Mapped[str | None] = mapped_column(
        ForeignKey("positions.id", ondelete="SET NULL"),
        nullable=True,
        comment="岗位",
    )
    job_level: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="职级（对标 salary_bands.job_level）"
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        comment="状态：pending待入职/probation试用/regular正式/intern实习/offboarded已离职",
    )
    hire_date: Mapped[date] = mapped_column(Date, nullable=False, comment="入职日期")
    regular_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="转正日期（转正异动写入）")
    offboard_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="离职日期（离职异动写入）")
    user_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, comment="关联 iam 用户（弱引用，租户内一对一，开通账号后回填）"
    )

    __table_args__ = (
        Index("uq_employees_tenant_no", "tenant_id", "employee_no", unique=True),
        Index("uq_employees_tenant_user", "tenant_id", "user_id", unique=True),
        Index("ix_employees_org_id", "org_id"),
        Index("ix_employees_position_id", "position_id"),
        Index("ix_employees_status", "tenant_id", "status"),
        {"comment": "员工主档表"},
    )


class EmployeeFieldGroup(BaseModel, TenantMixin, ActiveRecordMixin):
    """
    员工属性组（EAV 容器）

    预置 basic/education/contacts/work/custom 五组随 TenantInitializer seed 写入，
    管理端可扩展。
    """

    __tablename__ = "employee_field_groups"

    code: Mapped[str] = mapped_column(String(32), nullable=False, comment="组编码")
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="组名称")
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="排序")

    __table_args__ = (
        Index("uq_employee_field_groups_tenant_code", "tenant_id", "code", unique=True),
        {"comment": "员工属性组表"},
    )


class EmployeeFieldDefinition(BaseModel, TenantMixin, ActiveRecordMixin):
    """
    员工属性定义

    data_type 变更须校验存量值可解析；删除定义须先清理存量值；
    ext_data.sensitive 标记敏感字段（列表与详情按 hr:employee:sensitive 裁剪）。
    """

    __tablename__ = "employee_field_definitions"

    group_id: Mapped[str] = mapped_column(
        ForeignKey("employee_field_groups.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属属性组",
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="字段名")
    data_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="数据类型：string/integer/decimal/date_time/boolean/json",
    )
    ext_data: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="扩展配置：component/options/placeholder/min/max/unit/multiline/sensitive/self_editable",
    )
    is_require: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="是否必填"
    )
    can_edit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="是否可编辑"
    )
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="排序")

    __table_args__ = (
        Index("uq_employee_field_defs_tenant_group_name", "tenant_id", "group_id", "name", unique=True),
        Index("ix_employee_field_defs_group_id", "group_id"),
        {"comment": "员工属性定义表"},
    )


class EmployeeAttributeValue(BaseModel, TenantMixin, ActiveRecordMixin):
    """
    员工属性值（EAV 值表）

    value 恒存字符串：integer 存十进制串、boolean 存 "true"、json 存 JSON 串，
    解析统一走 parse_value（按 definition.data_type）。
    """

    __tablename__ = "employee_attribute_values"

    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        comment="员工",
    )
    definition_id: Mapped[str] = mapped_column(
        ForeignKey("employee_field_definitions.id", ondelete="CASCADE"),
        nullable=False,
        comment="属性定义",
    )
    value: Mapped[str | None] = mapped_column(Text, nullable=True, comment="属性值（恒存字符串）")

    __table_args__ = (
        Index(
            "uq_employee_attr_values_tenant_emp_def",
            "tenant_id",
            "employee_id",
            "definition_id",
            unique=True,
        ),
        Index("ix_employee_attr_values_employee_id", "employee_id"),
        {"comment": "员工属性值表"},
    )


class EmployeeContract(BaseModel, TenantMixin, ActiveRecordMixin):
    """
    员工合同

    到期日后状态由任务扫描自动置 expired；续签 = 旧合同区间闭合 + 新合同生效。
    """

    __tablename__ = "employee_contracts"

    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        comment="员工",
    )
    contract_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="合同编号")
    contract_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="合同类型")
    start_date: Mapped[date] = mapped_column(Date, nullable=False, comment="合同起始日")
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="合同截止日（空=无固定期限）")
    company: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="签约公司")
    signed_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="签订日期")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", comment="状态：active生效中/expired已到期/terminated已终止"
    )
    expiry_remind: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="到期提醒开关"
    )
    expiry_notified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="到期提醒已推送（防任务扫描重复通知）"
    )
    attachment: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="附件（MinIO 私有桶文件引用）"
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    __table_args__ = (
        Index("uq_employee_contracts_tenant_no", "tenant_id", "contract_no", unique=True),
        Index("ix_employee_contracts_employee_id", "employee_id"),
        Index("ix_employee_contracts_end_date", "tenant_id", "end_date"),
        {"comment": "员工合同表"},
    )


class EmployeeAttachment(BaseModel, TenantMixin, ActiveRecordMixin):
    """
    员工材料附件

    证件类 doc_type 受 hr:employee:sensitive 权限裁剪；下载写审计。
    """

    __tablename__ = "employee_attachments"

    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        comment="员工",
    )
    doc_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="档案类型：id_card/education/labor_contract/onboard/other",
    )
    file_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="文件 ID（MinIO 私有桶）")
    file_url: Mapped[str] = mapped_column(String(512), nullable=False, comment="文件引用路径")
    file_name: Mapped[str] = mapped_column(String(256), nullable=False, comment="文件名")

    __table_args__ = (
        Index("ix_employee_attachments_employee_id", "employee_id"),
        {"comment": "员工材料附件表"},
    )


class Position(BaseModel, TenantMixin, ActiveRecordMixin, SoftDeleteMixin):
    """
    岗位

    继承字段：BaseModel(id/created_at/updated_at) + TenantMixin(tenant_id)

    在岗人数为实时统计非落库字段；停用后不可被建档与招聘需求选中；
    在岗员工 > 0 不可删除。
    """

    __tablename__ = "positions"

    code: Mapped[str] = mapped_column(String(64), nullable=False, comment="岗位编码，租户内唯一")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="岗位名称")
    org_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, comment="所属组织（弱引用 iam.organizations，无外键）"
    )
    job_level: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="职级（如 P5/M2）")
    headcount: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="编制数")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", comment="状态：draft草稿/active生效/disabled停用"
    )

    __table_args__ = (
        Index("uq_positions_tenant_code", "tenant_id", "code", unique=True),
        Index("ix_positions_org_id", "org_id"),
        {"comment": "岗位表"},
    )


class EmployeeChange(BaseModel, TenantMixin, ActiveRecordMixin, OwnerMixin):
    """
    异动流水

    不提供删除；离职重复发起被状态机拒绝（409）；调薪流水与
    定薪区间闭合在同一事务内联动写入。变更摘要由前后快照差异派生。
    """

    __tablename__ = "employee_changes"

    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        comment="员工",
    )
    change_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="异动类型：hire/probate/transfer/level_change/salary_change/offboard",
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, comment="生效日期（不可早于当日）")
    before_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="变更前快照")
    after_data: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="变更后快照（离职原因/备注存于此）")
    operator_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="操作人（弱引用 iam 用户）")

    __table_args__ = (
        Index("ix_employee_changes_employee_id", "employee_id"),
        Index("ix_employee_changes_type", "tenant_id", "change_type"),
        {"comment": "员工异动流水表"},
    )
