"""岗位域 DTO"""

from framework.schemas import BaseModel, BasePaginatedQuery


class PositionPaginatedQuery(BasePaginatedQuery):
    """岗位分页查询"""

    org_id: str | None = None
    job_level: str | None = None
    status: str | None = None


class PositionCreate(BaseModel):
    """岗位创建"""

    code: str
    name: str
    org_id: str | None = None
    job_level: str | None = None
    headcount: int | None = None
    status: str = "active"


class PositionUpdate(BaseModel):
    """岗位更新"""

    code: str | None = None
    name: str | None = None
    org_id: str | None = None
    job_level: str | None = None
    headcount: int | None = None
    status: str | None = None


class PositionResponse(BaseModel):
    """岗位列表项（在岗人数实时统计非落库字段）"""

    id: str
    code: str
    name: str
    org_id: str | None = None
    job_level: str | None = None
    headcount: int | None = None
    active_employee_count: int = 0
    status: str
