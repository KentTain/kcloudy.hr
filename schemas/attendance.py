"""考勤域 Schema（考勤记录 / 总览统计 / 导入批次）"""

from __future__ import annotations

from datetime import date, datetime

from framework.schemas import BaseModel


# --------------------------------------------------------------------- 考勤记录


class AttendanceRecordResponse(BaseModel):
    id: str
    employee_id: str
    employee_no: str | None = None
    employee_name: str | None = None
    org_id: str | None = None
    work_date: date
    check_in_time: datetime | None = None
    check_out_time: datetime | None = None
    work_hours: float | None = None  # 小时
    overtime_hours: float | None = None  # 小时
    status: str  # normal/late/early_leave/late_early/absent/missing_card/leave/trip
    source: str  # excel/ai/leave
    remark: str | None = None


class AttendanceRecordPaginatedListResponse(BaseModel):
    total: int
    items: list[AttendanceRecordResponse]


# --------------------------------------------------------------------- 总览统计


class AttendanceStatsCards(BaseModel):
    """统计卡（随筛选联动）"""

    total_records: int
    attendance_count: int  # 出勤人次 = normal/late/early_leave/late_early/missing_card
    late_count: int  # 迟到人次 = late/late_early
    early_leave_count: int  # 早退人次 = early_leave/late_early
    absent_count: int  # 缺勤人次 = absent
    attendance_rate: float | None = None  # 出勤率（百分数，如 97.56；无记录为 None）


class AttendanceOrgStat(BaseModel):
    """部门统计行（部门名称经 iam 组织信息渲染）"""

    org_id: str
    total_records: int
    attendance_count: int
    late_count: int
    early_leave_count: int
    missing_card_count: int
    absent_count: int
    attendance_rate: float | None = None


class AttendanceStatsResponse(BaseModel):
    cards: AttendanceStatsCards
    org_slices: list[AttendanceOrgStat]


# --------------------------------------------------------------------- 导入批次


class AttendanceRowResult(BaseModel):
    """导入行级校验明细（data 承载解析出的标准字段值，供确认导入落库）"""

    row_index: int
    employee_no: str | None = None
    employee_name: str | None = None
    work_date: str | None = None
    parseable: bool = True  # 可解析（可导入）
    error: str | None = None  # 未匹配员工/字段缺失/格式错误原因
    selected: bool = True  # AI 通道勾选状态（默认勾选可解析行）
    data: dict | None = None  # 标准字段值（employee_no/work_date/check_in/...）


class AttendanceBatchResponse(BaseModel):
    id: str
    channel: str  # excel/ai
    status: str  # pending/parsing/parsed/completed/failed
    file_id: str | None = None
    filename: str | None = None
    field_mapping: dict | None = None
    row_results: list[AttendanceRowResult] | None = None
    new_count: int = 0
    overwrite_count: int = 0
    discard_count: int = 0
    fail_count: int = 0
    created_at: datetime | None = None


class AttendanceImportResult(BaseModel):
    """Excel 导入（dryRun 预检 / 正式导入）结果"""

    batch_id: str
    dry_run: bool
    row_results: list[AttendanceRowResult]
    new_count: int = 0
    overwrite_count: int = 0
    fail_count: int = 0
