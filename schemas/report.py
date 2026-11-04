"""报表域 Schema（人事仪表盘 / 离职率序列 / 招聘漏斗 / 薪酬分布 / 绩效分布）"""

from datetime import date

from framework.schemas import BaseModel

from hr.schemas.employee import EmployeeStatsResponse


class MetricRef(BaseModel):
    """指标口径引用（与 ontology 治理目录同源，ontology 缺席回退内置说明）"""

    metric: str  # attrition_rate / headcount_gap / perf_rating_distribution
    display_name: str
    description: str
    source: str  # ontology / builtin


class TrendPoint(BaseModel):
    """在编趋势点（按月，月末口径）"""

    month: str  # YYYY-MM
    count: int


class OrgDistributionItem(BaseModel):
    """组织分布（按在编人数）"""

    org_id: str | None = None
    count: int


class OverviewResponse(BaseModel):
    """人事仪表盘（当期指标实时 + 趋势快照/实时）"""

    cards: EmployeeStatsResponse
    headcount_trend: list[TrendPoint]
    org_distribution: list[OrgDistributionItem]
    metric_ref: MetricRef | None = None


class TurnoverPoint(BaseModel):
    """离职率序列点：离职率 = 当月离职人数 / 当月平均在编（百分数）"""

    month: str  # YYYY-MM
    offboarded: int
    avg_headcount: int
    rate: float | None = None


class TurnoverResponse(BaseModel):
    points: list[TurnoverPoint]
    metric_ref: MetricRef | None = None


class FunnelStageCount(BaseModel):
    """漏斗阶段计数（按投递申请计，与候选人页口径一致）"""

    stage: str
    count: int


class ChannelStageCount(BaseModel):
    """分渠道各阶段计数（渠道=候选人来源渠道；转化率前端逐段计算）"""

    channel: str | None = None
    stages: dict[str, int]


class RecruitingReportResponse(BaseModel):
    funnel: list[FunnelStageCount]
    channels: list[ChannelStageCount]


class CompDistItem(BaseModel):
    """薪酬分布聚合项（脱敏：仅 min/mid/max，无个人粒度）"""

    key: str | None = None  # job_level 或 org_id
    count: int
    min_amount: float
    mid_amount: float
    max_amount: float


class CompDistResponse(BaseModel):
    """薪酬分布（当期生效定薪按员工总额聚合；权限 hr:salary_package:read）"""

    by_level: list[CompDistItem]
    by_org: list[CompDistItem]


class CyclePerformanceItem(BaseModel):
    """closed 周期绩效汇总（评级分布按 calibrated_rating 优先回退 rating）"""

    cycle_id: str
    cycle_name: str
    end_date: date | None = None
    total: int
    avg_score: float | None = None
    ratings: dict[str, int]


class PerformanceReportResponse(BaseModel):
    """绩效报表（closed 周期评级分布 + 周期均分趋势，按周期截止日升序）"""

    cycles: list[CyclePerformanceItem]
    metric_ref: MetricRef | None = None


class AttritionRiskItem(BaseModel):
    """离职风险名单项（规则加权评分，实时计算）"""

    employee_id: str
    employee_no: str | None = None
    name: str
    org_id: str | None = None
    score: int
    level: str  # high / mid / low
    factors: list[str]


class AttritionRiskResponse(BaseModel):
    """离职风险名单（按风险分倒序，仅含得分 > 0 的在编员工）"""

    total: int  # 参评在编人数
    items: list[AttritionRiskItem]


class ReportAskRequest(BaseModel):
    """NL 问数请求"""

    question: str


class ReportAskResponse(BaseModel):
    """NL 问数响应（仅聚合口径，不返回明细行）"""

    metric: str
    domain: str
    metric_ref: str
    source: str
    data: dict | None = None
    answer: str
