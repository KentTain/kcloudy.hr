"""审批域 Schema（审批请求 / 审批流水）"""

from __future__ import annotations

from datetime import datetime

from framework.schemas import BaseModel, BasePaginatedQuery


class ApprovalRequestQuery(BasePaginatedQuery):
    biz_type: str | None = None
    status: str | None = None
    applicant_employee_id: str | None = None


class ApprovalRejectRequest(BaseModel):
    approve_comment: str


class ApprovalTransferRequest(BaseModel):
    owner_id: str


class ApprovalActionResponse(BaseModel):
    id: str
    action: str  # submit/approve/reject/cancel
    actor_id: str | None = None
    comment: str | None = None
    created_at: datetime | None = None


class ApprovalRequestResponse(BaseModel):
    id: str
    biz_type: str
    biz_ref_id: str | None = None
    applicant_employee_id: str
    employee_no: str | None = None
    employee_name: str | None = None
    org_id: str | None = None
    applicant_user_id: str | None = None
    owner_id: str | None = None
    title: str
    payload: dict | None = None
    status: str  # pending/approved/rejected/cancelled
    approver_id: str | None = None
    approve_comment: str | None = None
    approved_at: datetime | None = None
    created_at: datetime | None = None


class ApprovalRequestDetailResponse(ApprovalRequestResponse):
    actions: list[ApprovalActionResponse] = []


class ApprovalRequestPaginatedListResponse(BaseModel):
    total: int
    items: list[ApprovalRequestResponse]
