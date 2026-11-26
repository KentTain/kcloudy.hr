"""招聘域 Schema（需求/发布/候选人/投递/面试/Offer/聚合单）"""

from __future__ import annotations

from datetime import date, datetime

from framework.schemas import BaseModel, BasePaginatedQuery


# --------------------------------------------------------------------- 招聘需求


class RequisitionCreate(BaseModel):
    title: str
    org_id: str
    position_id: str | None = None
    headcount: int
    job_level: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    priority: str = "medium"
    jd: str | None = None
    channels: list[str] | None = None  # 非空时创建后立即发布


class RequisitionUpdate(BaseModel):
    title: str | None = None
    org_id: str | None = None
    position_id: str | None = None
    headcount: int | None = None
    job_level: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    priority: str | None = None
    jd: str | None = None


class RequisitionQuery(BasePaginatedQuery):
    status: str | None = None
    priority: str | None = None
    org_id: str | None = None


class PostingResponse(BaseModel):
    id: str
    channel: str
    status: str
    external_post_id: str | None = None
    published_at: datetime | None = None


class RequisitionResponse(BaseModel):
    id: str
    req_no: str
    title: str
    org_id: str
    position_id: str | None = None
    headcount: int
    job_level: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    priority: str
    status: str
    jd: str | None = None
    filled_count: int
    postings: list[PostingResponse] = []


class RequisitionPaginatedListResponse(BaseModel):
    total: int
    items: list[RequisitionResponse]


class FunnelStat(BaseModel):
    stage: str
    count: int


class FunnelResponse(BaseModel):
    requisition_id: str | None = None
    stats: list[FunnelStat]


# --------------------------------------------------------------------- 候选人


class CandidateCreate(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    source_channel: str = "manual"
    requisition_id: str | None = None  # 关联需求时同步产生投递


class CandidateUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    is_blacklist: bool | None = None


class CandidateQuery(BasePaginatedQuery):
    stage: str | None = None
    channel: str | None = None
    requisition_id: str | None = None
    include_blacklist: bool = False


class CandidateResponse(BaseModel):
    id: str
    name: str
    phone: str | None = None
    email: str | None = None
    source_channel: str | None = None
    is_blacklist: bool
    profile: dict | None = None
    resume_file: str | None = None


class CandidatePaginatedListResponse(BaseModel):
    total: int
    items: list[CandidateResponse]


class MergeSuggestion(BaseModel):
    candidate_id: str
    target_id: str
    matched_by: str  # phone/email


class StageUpdate(BaseModel):
    stage: str
    remark: str | None = None


class StageHistoryEntry(BaseModel):
    stage: str
    operator_id: str | None = None
    operated_at: datetime
    remark: str | None = None


class ApplicationResponse(BaseModel):
    id: str
    candidate_id: str
    candidate_name: str | None = None
    requisition_id: str
    requisition_title: str | None = None
    stage: str
    stage_history: list[StageHistoryEntry] = []
    match_score: float | None = None
    apply_time: datetime
    employee_id: str | None = None


class ApplicationPaginatedListResponse(BaseModel):
    total: int
    items: list[ApplicationResponse]


# --------------------------------------------------------------------- 面试


class InterviewCreate(BaseModel):
    application_id: str
    interviewer_id: str
    scheduled_at: datetime
    interview_form: str = "onsite"


class InterviewUpdate(BaseModel):
    scheduled_at: datetime | None = None  # 改期（通知面试官）
    result: str | None = None  # pass/fail
    feedback: str | None = None


class InterviewResponse(BaseModel):
    id: str
    application_id: str
    round: int
    interviewer_id: str
    scheduled_at: datetime
    interview_form: str
    result: str
    feedback: str | None = None
    ai_summary: str | None = None


class InterviewPaginatedListResponse(BaseModel):
    total: int
    items: list[InterviewResponse]


# --------------------------------------------------------------------- Offer


class OfferCreate(BaseModel):
    application_id: str
    salary_snapshot: dict  # item_code → 金额（元）
    valid_until: datetime | None = None


class OfferResponse(BaseModel):
    id: str
    application_id: str
    salary_snapshot: dict
    status: str
    valid_until: datetime | None = None
    sent_at: datetime | None = None


class OfferOnboardCreate(BaseModel):
    """入职转化建档（hire_date 缺省今日；岗位缺省沿用需求配置）"""

    hire_date: date | None = None
    position_id: str | None = None


# --------------------------------------------------------------------- 招聘聚合单（流程测试载体）


class BundleOfferInput(BaseModel):
    """聚合行内 Offer 孙对象（类型化定薪快照，落库进 salary_snapshot）"""

    monthly_salary: float
    sign_on_bonus: float | None = None
    year_end_bonus: float | None = None
    valid_until: datetime | None = None


class BundleApplicationInput(BaseModel):
    """聚合明细行（内嵌候选人字段；application_id 仅编辑行匹配用，创建时忽略）"""

    application_id: str | None = None
    candidate_name: str
    candidate_phone: str | None = None
    candidate_email: str | None = None
    candidate_source_channel: str = "manual"
    match_score: float | None = None
    offer: BundleOfferInput | None = None


class RequisitionBundleCreate(BaseModel):
    """聚合单创建：父=需求字段，applications=子明细，行内 offer=孙对象（1:1）"""

    title: str
    org_id: str
    position_id: str | None = None
    headcount: int
    job_level: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    priority: str = "medium"
    jd: str | None = None
    applications: list[BundleApplicationInput] = []


class RequisitionBundleUpdate(BaseModel):
    """聚合单编辑：父字段全可选；明细按行 upsert（带 id 更新/不带新建/缺失删除）"""

    title: str | None = None
    org_id: str | None = None
    position_id: str | None = None
    headcount: int | None = None
    job_level: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    priority: str | None = None
    jd: str | None = None
    applications: list[BundleApplicationInput] = []


class BundleOfferResponse(BaseModel):
    offer_id: str
    monthly_salary: float
    sign_on_bonus: float | None = None
    year_end_bonus: float | None = None
    valid_until: datetime | None = None
    status: str


class BundleApplicationResponse(BaseModel):
    application_id: str
    candidate_id: str
    candidate_name: str
    candidate_phone: str | None = None
    candidate_email: str | None = None
    candidate_source_channel: str | None = None
    stage: str
    match_score: float | None = None
    apply_time: datetime
    offer: BundleOfferResponse | None = None


class RequisitionBundleDetailResponse(BaseModel):
    id: str
    req_no: str
    title: str
    org_id: str
    position_id: str | None = None
    headcount: int
    job_level: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    priority: str
    status: str
    jd: str | None = None
    applications: list[BundleApplicationResponse] = []


class RequisitionBundleListItem(BaseModel):
    id: str
    req_no: str
    title: str
    org_id: str
    headcount: int
    priority: str
    status: str
    application_count: int
    offer_count: int
