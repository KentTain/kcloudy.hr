"""审批域模型（审批请求 / 审批流水）"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from framework.database import ActiveRecordMixin, OwnerMixin, TenantMixin

from hr.models import BaseModel


class ApprovalRequest(BaseModel, TenantMixin, ActiveRecordMixin, OwnerMixin):
    """
    审批请求（hr 域内通用审批模型）

    biz_type 区分业务类型，payload 由对应 handler 解释；审批采用池模式
    （不预指定审批人，具备 hr:approval:approve 权限者处理）；通过时回调
    handler 应用业务变更，失败整体回滚保持 pending；终态只读。
    """

    __tablename__ = "approval_requests"

    biz_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="业务类型：profile_change（预留 leave 等）"
    )
    biz_ref_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, comment="关联业务单据（可空=payload 自包含申请）"
    )
    applicant_employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        comment="申请人（员工）",
    )
    applicant_user_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, comment="申请人（iam 用户，可空弱引用）"
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False, comment="单据标题")
    payload: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="业务载荷（handler 解释，如 profile_change 属性值变更集）"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", comment="状态：pending/approved/rejected/cancelled"
    )
    approver_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, comment="审批人（弱引用 iam 用户）"
    )
    approve_comment: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="审批意见（驳回必填）")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="审批时间")

    __table_args__ = (
        Index("ix_approval_requests_tenant_status", "tenant_id", "status"),
        Index("ix_approval_requests_tenant_applicant", "tenant_id", "applicant_employee_id"),
        {"comment": "审批请求表"},
    )


class ApprovalAction(BaseModel, TenantMixin, ActiveRecordMixin):
    """审批流水（提交/通过/驳回/撤销逐次留痕，不可篡改）"""

    __tablename__ = "approval_actions"

    request_id: Mapped[str] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="CASCADE"),
        nullable=False,
        comment="审批请求",
    )
    action: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="动作：submit/approve/reject/cancel"
    )
    actor_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, comment="操作人（弱引用 iam 用户；提交为申请人）"
    )
    comment: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="意见（驳回必填）")

    __table_args__ = (
        Index("ix_approval_actions_tenant_request", "tenant_id", "request_id"),
        {"comment": "审批流水表"},
    )
