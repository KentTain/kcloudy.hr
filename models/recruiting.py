"""招聘域模型（需求 / 渠道发布 / 候选人 / 投递 / Offer / 面试）"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from framework.database import ActiveRecordMixin, SoftDeleteMixin, TenantMixin

from hr.models import BaseModel


class JobRequisition(BaseModel, TenantMixin, ActiveRecordMixin, SoftDeleteMixin):
    """
    招聘需求

    filled_count ≥ headcount 自动置 filled；关闭后拒绝投递与流转；
    org_id 为跨模块弱引用无外键。
    """

    __tablename__ = "job_requisitions"

    req_no: Mapped[str] = mapped_column(String(32), nullable=False, comment="需求编号，自动生成，租户内唯一")
    title: Mapped[str] = mapped_column(String(128), nullable=False, comment="职位名称")
    org_id: Mapped[str] = mapped_column(
        String(36), nullable=False, comment="招聘部门（弱引用 iam.organizations，无外键）"
    )
    position_id: Mapped[str | None] = mapped_column(
        ForeignKey("positions.id", ondelete="SET NULL"),
        nullable=True,
        comment="岗位",
    )
    headcount: Mapped[int] = mapped_column(Integer, nullable=False, comment="招聘人数")
    job_level: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="要求职级")
    salary_min: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True, comment="薪酬区间下限（元/月）")
    salary_max: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True, comment="薪酬区间上限（元/月）")
    priority: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="优先级：low/medium/high/urgent"
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        comment="状态：draft/recruiting/partial/filled/closed",
    )
    jd: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JD（富文本）")
    filled_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="已入职人数")

    __table_args__ = (
        Index("uq_job_requisitions_tenant_no", "tenant_id", "req_no", unique=True),
        Index("ix_job_requisitions_org_id", "org_id"),
        Index("ix_job_requisitions_status", "tenant_id", "status"),
        {"comment": "招聘需求表"},
    )

    postings: Mapped[list["JobPosting"]] = relationship(
        back_populates="requisition",
    )


class JobPosting(BaseModel, TenantMixin, ActiveRecordMixin):
    """职位发布（需求 × 渠道）；external_post_id 由渠道归集异步任务回写。"""

    __tablename__ = "job_postings"

    requisition_id: Mapped[str] = mapped_column(
        ForeignKey("job_requisitions.id", ondelete="CASCADE"),
        nullable=False,
        comment="招聘需求",
    )
    channel: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="渠道：internal/zhilian/job51/liepin"
    )
    external_post_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="渠道职位映射 ID（异步发布任务回写）"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="publishing", comment="状态：publishing/published/offline"
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="发布时间")

    __table_args__ = (
        Index("uq_job_postings_tenant_req_channel", "tenant_id", "requisition_id", "channel", unique=True),
        {"comment": "职位发布表"},
    )

    requisition: Mapped["JobRequisition"] = relationship(back_populates="postings")


class Candidate(BaseModel, TenantMixin, ActiveRecordMixin, SoftDeleteMixin):
    """
    候选人主档

    同手机号/邮箱重复档靠合并机制归并（需 hr:candidate:merge），不设唯一约束；
    profile 为 AI 归一结构化简历（解析任务回写）。
    """

    __tablename__ = "candidates"

    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="姓名")
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="手机号（脱敏回显）")
    email: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="邮箱")
    source_channel: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="来源渠道（渠道编码或 manual/internal）"
    )
    external_candidate_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="渠道候选人 ID（归集幂等 upsert 键；手工录入为空）"
    )
    profile: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="AI 归一结构化简历（教育/经历/技能/亮点风险摘要）"
    )
    resume_file: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="简历附件（MinIO，受控下载写审计）"
    )
    is_blacklist: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="黑名单标识（不参与默认筛选）"
    )

    __table_args__ = (
        Index("ix_candidates_phone", "tenant_id", "phone"),
        Index("ix_candidates_email", "tenant_id", "email"),
        Index(
            "uq_candidates_tenant_channel_ext",
            "tenant_id",
            "source_channel",
            "external_candidate_id",
            unique=True,
            postgresql_where=text("external_candidate_id IS NOT NULL"),
        ),
        {"comment": "候选人主档表"},
    )


class CandidateApplication(BaseModel, TenantMixin, ActiveRecordMixin):
    """
    投递申请（三段漏斗载体）

    stage_history 追加式流转史；employee_id 在办理入职建档后回填。
    """

    __tablename__ = "candidate_applications"

    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        comment="候选人",
    )
    requisition_id: Mapped[str] = mapped_column(
        ForeignKey("job_requisitions.id", ondelete="CASCADE"),
        nullable=False,
        comment="招聘需求",
    )
    stage: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="pending_screening",
        comment="阶段：pending_screening/screening_passed/interviewing/pre_hire/offered/"
        "pre_onboard/onboarded/onboard_abandoned/rejected/withdrawn",
    )
    stage_history: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, comment="流转史（阶段/操作人/时间/备注）"
    )
    match_score: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True, comment="AI 人岗匹配分（JD+profile 打分）"
    )
    apply_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="投递时间")
    employee_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        comment="入职建档后的员工回填",
    )

    __table_args__ = (
        Index("ix_candidate_applications_candidate_id", "candidate_id"),
        Index("ix_candidate_applications_requisition_id", "requisition_id"),
        Index("ix_candidate_applications_stage", "tenant_id", "stage"),
        {"comment": "候选人投递申请表"},
    )


class Offer(BaseModel, TenantMixin, ActiveRecordMixin, SoftDeleteMixin):
    """
    Offer 单（一申请至多一 offer）

    send → 申请置 offered；accept → 申请置 pre_onboard。
    """

    __tablename__ = "offers"

    application_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_applications.id", ondelete="CASCADE"),
        nullable=False,
        comment="投递申请",
    )
    salary_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="定薪方案快照（item_code→金额）")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", comment="状态：pending/sent/accepted/rejected"
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="有效期")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="发送时间")

    __table_args__ = (
        Index("uq_offers_application", "application_id", unique=True),
        {"comment": "Offer 单表"},
    )


class Interview(BaseModel, TenantMixin, ActiveRecordMixin):
    """面试；轮次自动 +1 不重复，改期更新时间并通知面试官。"""

    __tablename__ = "interviews"

    application_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_applications.id", ondelete="CASCADE"),
        nullable=False,
        comment="投递申请",
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False, comment="轮次（自动 +1）")
    interviewer_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
        comment="面试官（默认用人经理）",
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="面试时间")
    interview_form: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="形式：onsite/video/phone"
    )
    result: Mapped[str] = mapped_column(
        String(10), nullable=False, default="pending", comment="结果：pending/pass/fail"
    )
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True, comment="面试反馈")
    ai_summary: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="AI 纪要（基于反馈与简历生成，失败可后补）"
    )

    __table_args__ = (
        Index("uq_interviews_tenant_app_round", "tenant_id", "application_id", "round", unique=True),
        Index("ix_interviews_interviewer_id", "interviewer_id"),
        Index("ix_interviews_scheduled_at", "tenant_id", "scheduled_at"),
        {"comment": "面试表"},
    )
