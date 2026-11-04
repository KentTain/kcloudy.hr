"""假勤域 Schema（假期类型 / 假期余额 / 请假单）"""

from __future__ import annotations

from datetime import datetime

from framework.schemas import BaseModel


# --------------------------------------------------------------------- 假期类型


class LeaveTypeCreate(BaseModel):
    code: str
    name: str
    unit: str  # day/hour
    paid: bool = True
    quota_rule: str  # annual_fixed/manual
    default_quota: float | None = None  # 单位随 unit


class LeaveTypeUpdate(BaseModel):
    name: str | None = None
    unit: str | None = None
    paid: bool | None = None
    quota_rule: str | None = None
    default_quota: float | None = None
    status: str | None = None  # enabled/disabled


class LeaveTypeResponse(BaseModel):
    id: str
    code: str
    name: str
    unit: str
    paid: bool
    quota_rule: str
    default_quota: float | None = None
    status: str


class LeaveTypePaginatedListResponse(BaseModel):
    total: int
    items: list[LeaveTypeResponse]


# --------------------------------------------------------------------- 假期余额


class LeaveBalanceResponse(BaseModel):
    id: str
    employee_id: str
    employee_no: str | None = None
    employee_name: str | None = None
    org_id: str | None = None
    leave_type_id: str
    leave_type_code: str | None = None
    leave_type_name: str | None = None
    unit: str | None = None
    year: int
    total_quota: float  # 单位随类型 unit
    used: float
    frozen: float
    balance: float  # total_quota − used − frozen


class LeaveBalancePaginatedListResponse(BaseModel):
    total: int
    items: list[LeaveBalanceResponse]


class LeaveBalanceAdjust(BaseModel):
    total_quota: float


# --------------------------------------------------------------------- 请假单


class LeaveRequestCreate(BaseModel):
    leave_type_id: str
    start_time: datetime
    end_time: datetime
    reason: str
    attachment_file: str | None = None  # common/upload 通道，可选


class LeaveRejectRequest(BaseModel):
    approve_comment: str


class LeaveTransferRequest(BaseModel):
    owner_id: str


class LeaveRequestResponse(BaseModel):
    id: str
    employee_id: str
    employee_no: str | None = None
    employee_name: str | None = None
    org_id: str | None = None
    owner_id: str | None = None
    leave_type_id: str
    leave_type_code: str | None = None
    leave_type_name: str | None = None
    unit: str | None = None
    start_time: datetime
    end_time: datetime
    duration: float  # 单位随类型（day=闭区间天数 / hour=时间差）
    reason: str
    attachment_file: str | None = None
    status: str  # pending/approved/rejected/cancelled
    approver_id: str | None = None
    approve_comment: str | None = None
    approved_at: datetime | None = None
    created_at: datetime | None = None


class LeaveRequestPaginatedListResponse(BaseModel):
    total: int
    items: list[LeaveRequestResponse]
