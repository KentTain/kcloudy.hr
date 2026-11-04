"""薪酬域 Schema（薪酬项/类别字典/职级薪带/定薪调薪/发薪批次）

金额口径：全部为元（DECIMAL(12,2)），响应明示单位，无浮点裸算。
"""

from __future__ import annotations

from datetime import date

from framework.schemas import BaseModel


# --------------------------------------------------------------------- 薪酬项


class SalaryItemCreate(BaseModel):
    code: str
    name: str
    category: str
    ext_data: dict | None = None  # 规则元数据：taxable/social_security_base/monthly_fixed/unit
    sort: int = 0


class SalaryItemUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    ext_data: dict | None = None
    can_edit: bool | None = None  # false=停用
    sort: int | None = None


class SalaryItemResponse(BaseModel):
    id: str
    code: str
    name: str
    category: str
    ext_data: dict | None = None
    can_edit: bool
    sort: int


class SalaryItemPaginatedListResponse(BaseModel):
    total: int
    items: list[SalaryItemResponse]


class SalaryCategoriesResponse(BaseModel):
    categories: list[str]


class SalaryCategoriesUpdate(BaseModel):
    categories: list[str]


# --------------------------------------------------------------------- 职级薪带


class SalaryBandCreate(BaseModel):
    job_level: str
    min_salary: float  # 元/月
    mid_salary: float  # 元/月
    max_salary: float  # 元/月
    effective_from: date
    effective_to: date | None = None


class SalaryBandUpdate(BaseModel):
    min_salary: float | None = None
    mid_salary: float | None = None
    max_salary: float | None = None
    effective_from: date | None = None
    effective_to: date | None = None


class SalaryBandResponse(BaseModel):
    id: str
    job_level: str
    min_salary: float
    mid_salary: float
    max_salary: float
    effective_from: date
    effective_to: date | None = None


class SalaryBandPaginatedListResponse(BaseModel):
    total: int
    items: list[SalaryBandResponse]


# --------------------------------------------------------------------- 定薪调薪


class SalaryPackageCreate(BaseModel):
    """调薪（一事一流水：按薪酬项逐行闭合旧区间 + 生成新区间）"""

    items: list[SalaryPackageItemCreate]
    reason: str = "adjust"  # hire/adjust/promotion/perf
    effective_from: date


class SalaryPackageItemCreate(BaseModel):
    item_id: str
    amount: float  # 元/月


class SalaryPackageResponse(BaseModel):
    id: str
    employee_id: str
    item_id: str
    item_code: str | None = None
    item_name: str | None = None
    category: str | None = None
    amount: float  # 元/月
    reason: str
    effective_from: date
    effective_to: date | None = None


class SalaryPackagePaginatedListResponse(BaseModel):
    total: int
    items: list[SalaryPackageResponse]


class BandComparison(BaseModel):
    """薪带对标（方案总额相对职级带宽位置）"""

    job_level: str
    total: float  # 元/月
    band_min: float | None = None
    band_max: float | None = None
    position: str  # below/within/above/none（none=无生效薪带）


class ComparisonResponse(BaseModel):
    """定薪与薪带对标统计（部门/职级切片）"""

    slices: list[ComparisonSlice]


class ComparisonSlice(BaseModel):
    job_level: str
    org_id: str | None = None
    employee_count: int
    avg_total: float  # 元/月
    band_min: float | None = None
    band_max: float | None = None


# --------------------------------------------------------------------- 发薪批次


class PayrollRunCreate(BaseModel):
    period: str  # YYYY-MM


class PayrollRunResponse(BaseModel):
    id: str
    period: str
    status: str
    total_amount: float | None = None  # 元
    employee_count: int | None = None
    pay_date: date | None = None


class PayrollRunPaginatedListResponse(BaseModel):
    total: int
    items: list[PayrollRunResponse]


class PayrollEntryUpdate(BaseModel):
    amount: float  # 元
    note: str | None = None


class PayrollEntryResponse(BaseModel):
    id: str
    run_id: str
    employee_id: str
    employee_no: str | None = None
    employee_name: str | None = None
    item_id: str
    item_code: str
    amount: float  # 元
    note: str | None = None


class PayrollEntryPaginatedListResponse(BaseModel):
    total: int
    items: list[PayrollEntryResponse]
