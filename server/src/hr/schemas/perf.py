"""绩效域 Schema（考核周期 / 绩效目标 / 绩效评估 / 评级分布）"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from framework.schemas import BasePaginatedQuery, BaseModel


class PerfCycleQuery(BasePaginatedQuery):
    status: str | None = None
    date_from: date | None = None
    date_to: date | None = None


class PerfCycleCreate(BaseModel):
    name: str
    start_date: date
    end_date: date


class PerfCycleUpdate(BaseModel):
    name: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class PerfCycleResponse(BaseModel):
    id: str
    name: str
    start_date: date
    end_date: date
    status: str  # draft/active/scoring/calibrating/closed
    goal_count: int = 0
    review_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PerfCyclePaginatedListResponse(BaseModel):
    total: int
    items: list[PerfCycleResponse]


class PerfGoalCreateItem(BaseModel):
    code: str
    name: str
    weight: Decimal
    target_value: str | None = None


class PerfGoalBatchCreate(BaseModel):
    """目标整批提交：同员工同周期一次提交全部目标，权重合计须恰好 100"""

    cycle_id: str
    employee_id: str
    goals: list[PerfGoalCreateItem]


class PerfGoalUpdate(BaseModel):
    name: str | None = None
    weight: Decimal | None = None
    target_value: str | None = None


class PerfGoalProgressUpdate(BaseModel):
    progress: int
    actual_value: str | None = None


class PerfGoalResponse(BaseModel):
    id: str
    cycle_id: str
    employee_id: str
    employee_no: str | None = None
    employee_name: str | None = None
    code: str
    name: str
    weight: Decimal
    target_value: str | None = None
    actual_value: str | None = None
    progress: int
    status: str  # open/completed
    created_at: datetime | None = None


class PerfGoalPaginatedListResponse(BaseModel):
    total: int
    items: list[PerfGoalResponse]


class PerfRatingCount(BaseModel):
    count: int
    percent: float


class PerfDistributionResponse(BaseModel):
    """评级分布（校准参考；口径 calibrated_rating 优先回退 rating；rules 为强制分布规则线）"""

    cycle_id: str
    total: int
    ratings: dict[str, PerfRatingCount]
    rules: dict[str, float] | None = None


class PerfReviewQuery(BasePaginatedQuery):
    cycle_id: str | None = None
    status: str | None = None  # pending/submitted/calibrated
    reviewer_employee_id: str | None = None


class PerfReviewCreateItem(BaseModel):
    employee_id: str
    reviewer_employee_id: str


class PerfReviewBatchCreate(BaseModel):
    """批量发起评估：scoring 态，周期 × 被评人唯一，已存在的跳过"""

    cycle_id: str
    items: list[PerfReviewCreateItem]


class PerfReviewCreateResponse(BaseModel):
    cycle_id: str
    created: int
    skipped: int


class PerfReviewScoreUpdate(BaseModel):
    score: Decimal
    rating: str  # S/A/B/C/D
    self_score: Decimal | None = None
    comment: str | None = None


class PerfReviewCalibrateUpdate(BaseModel):
    rating: str  # S/A/B/C/D
    comment: str


class PerfReviewResponse(BaseModel):
    id: str
    cycle_id: str
    cycle_status: str | None = None
    employee_id: str
    employee_no: str | None = None
    employee_name: str | None = None
    reviewer_employee_id: str
    reviewer_name: str | None = None
    goal_count: int = 0
    weighted_progress: float = 0.0
    self_score: Decimal | None = None
    score: Decimal | None = None
    rating: str | None = None
    calibrated_rating: str | None = None
    calibration_comment: str | None = None
    calibrated_at: datetime | None = None
    coefficient: Decimal | None = None
    status: str  # pending/submitted/calibrated
    created_at: datetime | None = None


class PerfReviewPaginatedListResponse(BaseModel):
    total: int
    items: list[PerfReviewResponse]
