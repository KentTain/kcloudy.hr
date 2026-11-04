"""员工自助/团队工作台 Schema（console 层：变更申请 / 目标进度 / 团队评分）"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from framework.schemas import BaseModel


class ChangeRequestItem(BaseModel):
    definition_id: str
    new_value: Any = None


class ChangeRequestCreate(BaseModel):
    title: str
    changes: list[ChangeRequestItem]


class TeamReviewScoreUpdate(BaseModel):
    score: Decimal
    rating: str  # S/A/B/C/D
    self_score: Decimal | None = None
