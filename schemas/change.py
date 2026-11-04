"""异动域 DTO（流水检索 / 发起异动）"""

from datetime import date
from typing import Any

from framework.schemas import BaseModel, BasePaginatedQuery


class ChangePaginatedQuery(BasePaginatedQuery):
    """异动流水分页查询"""

    employee_id: str | None = None
    change_type: str | None = None
    org_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class ChangeCreate(BaseModel):
    """发起异动（转正/调岗/调薪/离职）"""

    employee_id: str
    change_type: str
    effective_date: date
    # 调岗
    org_id: str | None = None
    position_id: str | None = None
    job_level: str | None = None
    # 调薪（薪酬项 × 新金额快照，随流水落 after_data；定薪区间闭合随薪酬域接入）
    salary_items: list[dict[str, Any]] | None = None
    # 离职
    reason: str | None = None
    remark: str | None = None


class ChangeTransferRequest(BaseModel):
    """移交业务归属"""

    owner_id: str


class ChangeResponse(BaseModel):
    """异动流水"""

    id: str
    employee_id: str
    owner_id: str | None = None
    change_type: str
    before_data: dict[str, Any] | None = None
    after_data: dict[str, Any] | None = None
    effective_date: date
    operator_id: str | None = None
