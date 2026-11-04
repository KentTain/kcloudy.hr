"""员工域 DTO（花名册查询 / 建档编辑 / 统计 / 开通账号 / 详情聚合）"""

from datetime import date

from framework.schemas import BaseModel, BasePaginatedQuery


class EmployeePaginatedQuery(BasePaginatedQuery):
    """员工分页查询"""

    org_id: str | None = None
    status: str | None = None
    position_id: str | None = None
    job_level: str | None = None


class EmployeeStatsResponse(BaseModel):
    """员工统计卡（在编/试用/本月新入职/离职率）"""

    active_count: int = 0
    probation_count: int = 0
    month_hired_count: int = 0
    turnover_rate: float = 0.0


class EmployeeCreate(BaseModel):
    """入职建档"""

    name: str
    gender: str | None = None
    birth_date: date | None = None
    id_card: str | None = None
    bank_card: str | None = None
    bank_name: str | None = None
    phone: str | None = None
    work_email: str | None = None
    org_id: str | None = None
    position_id: str | None = None
    job_level: str | None = None
    status: str = "pending"
    hire_date: date
    attribute_values: dict[str, object] | None = None


class EmployeeUpdate(BaseModel):
    """员工编辑（敏感字段提交掩码/空表示保留原值）"""

    name: str | None = None
    gender: str | None = None
    birth_date: date | None = None
    id_card: str | None = None
    bank_card: str | None = None
    bank_name: str | None = None
    phone: str | None = None
    work_email: str | None = None
    org_id: str | None = None
    position_id: str | None = None
    job_level: str | None = None
    status: str | None = None


class EmployeeResponse(BaseModel):
    """员工列表项"""

    id: str
    employee_no: str
    name: str
    gender: str | None = None
    phone: str | None = None
    work_email: str | None = None
    org_id: str | None = None
    position_id: str | None = None
    job_level: str | None = None
    status: str
    hire_date: date
    regular_date: date | None = None
    offboard_date: date | None = None
    user_id: str | None = None
    has_account: bool = False


class SensitiveView(BaseModel):
    """敏感字段明文视图（有 hr:employee:sensitive 权限时返回，明文查看写审计）"""

    id_card: str | None = None
    bank_card: str | None = None


class EmployeeDetailResponse(EmployeeResponse):
    """员工详情（敏感字段掩码，明文经 sensitive 视图接口）"""

    birth_date: date | None = None
    id_card_masked: str | None = None
    bank_card_masked: str | None = None
    bank_name: str | None = None


class AccountOpenResponse(BaseModel):
    """开通系统账号结果（初始密码一次性回显）"""

    employee_id: str
    user_id: str
    username: str
    initial_password: str


class EmployeeImportRow(BaseModel):
    """批量导入行"""

    name: str
    gender: str | None = None
    birth_date: date | None = None
    id_card: str | None = None
    phone: str | None = None
    work_email: str | None = None
    org_id: str | None = None
    position_id: str | None = None
    job_level: str | None = None
    hire_date: date
    status: str = "pending"


class EmployeeImportRequest(BaseModel):
    """批量导入请求（dryRun 预检不落库）"""

    dry_run: bool = False
    rows: list[EmployeeImportRow]


class EmployeeImportRowResult(BaseModel):
    """导入行结果"""

    row_index: int
    success: bool
    employee_no: str | None = None
    error: str | None = None


class EmployeeImportResponse(BaseModel):
    """导入结果"""

    dry_run: bool
    total: int
    success_count: int
    failure_count: int
    rows: list[EmployeeImportRowResult]
