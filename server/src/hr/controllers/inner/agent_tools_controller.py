"""hr inner agent 工具面（对齐 ontology E2.1 模式）

- 面类型=inner（工具运行时无用户 JWT）+ X-Tenant-Id fail-closed（缺失拒绝）。
- 全 GET 只读：工具桥 read_only 按 HTTP method 分级自动免审，无需凭证注册。
- 按 LLM 消费习惯设计：动词明确的工具命名、query 参数少而语义化、
  OpenAPI summary 按工具描述写法编写、统一 tag=agent-tools。
- 裸 dict 出站（无 code/data 包装），成功响应不携带 error 键。

消费链路：ai 接口库 OpenAPI 导入 → tool-bus 装配 → hermes agent 工具调用 →
POST /ai/inner/v1/tool-bus/invoke → HTTP GET 本面（X-Tenant-Id 回传）。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import ORJSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ForbiddenError, NotFoundError
from framework.database.dependencies import get_db_session

from hr.services.agent_tool_service import agent_tool_service

router = APIRouter(prefix="/inner/v1")


def _to_http(exc: Exception) -> HTTPException:
    """领域异常 → HTTP（403 无租户上下文 fail-closed / 404 不存在 / 400 参数）"""
    if isinstance(exc, ForbiddenError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, BadRequestError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=404, detail=str(exc))


@router.get(
    "/agent-tools/headcount",
    response_class=ORJSONResponse,
    tags=["agent-tools"],
    summary="查组织编制与在编概览：返回编制数（生效岗位合计）、在编人数"
    "（试用期+正式）、缺编差额。适合『XX 组织还缺几个人』『现在有多少在职』"
    "类问题；org_id 缺省全公司口径，给定时含子组织。",
)
async def headcount(
    org_id: str | None = Query(None, description="组织 ID（缺省全公司，含子组织）"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """组织编制与在编概览"""
    try:
        return await agent_tool_service.headcount(session, org_id=org_id)
    except ForbiddenError as exc:
        raise _to_http(exc) from exc


@router.get(
    "/agent-tools/candidates",
    response_class=ORJSONResponse,
    tags=["agent-tools"],
    summary="检索候选人：按姓名/手机号/邮箱关键词匹配，可按投递阶段过滤"
    "（如 interviewing 面试中）。联系方式一律脱敏展示。适合『找一下某位候选人』"
    "『面试中有哪些人』类问题。",
)
async def search_candidates(
    q: str | None = Query(None, description="关键词（姓名/手机号/邮箱匹配）"),
    stage: str | None = Query(
        None,
        description="投递阶段过滤：pending_screening/screening_passed/interviewing/"
        "pre_hire/offered/pre_onboard/onboarded/rejected/withdrawn",
    ),
    limit: int = Query(10, ge=1, le=20, description="返回条数上限"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """候选人检索（脱敏口径）"""
    try:
        return await agent_tool_service.search_candidates(
            session, q=q, stage=stage, limit=limit
        )
    except ForbiddenError as exc:
        raise _to_http(exc) from exc


@router.get(
    "/agent-tools/recruiting-funnel",
    response_class=ORJSONResponse,
    tags=["agent-tools"],
    summary="查招聘漏斗统计：按十阶段（初筛→面试→拟录用→Offer→入职等）返回"
    "投递计数。requisition_id 缺省为全租户汇总，给定时为单个招聘需求的漏斗"
    "（并返回需求标题）。适合『招聘进展如何』『这个岗位漏斗情况』类问题。",
)
async def recruiting_funnel(
    requisition_id: str | None = Query(
        None, description="招聘需求 ID（缺省全租户汇总口径）"
    ),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """招聘漏斗统计"""
    try:
        return await agent_tool_service.recruiting_funnel(
            session, requisition_id=requisition_id
        )
    except (ForbiddenError, NotFoundError) as exc:
        raise _to_http(exc) from exc


@router.get(
    "/agent-tools/turnover-stats",
    response_class=ORJSONResponse,
    tags=["agent-tools"],
    summary="查离职率序列：近 N 月（缺省 6，上限 12）逐月返回离职人数、平均在编"
    "与百分数比率（与报表分析同源口径）。适合『最近离职率高吗』『上月走了几个人』"
    "类问题。",
)
async def turnover_stats(
    months: int = Query(6, ge=1, le=12, description="回溯月数（1-12）"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """近 N 月离职率序列"""
    try:
        return await agent_tool_service.turnover_stats(session, months=months)
    except ForbiddenError as exc:
        raise _to_http(exc) from exc


@router.get(
    "/agent-tools/comp-distribution",
    response_class=ORJSONResponse,
    tags=["agent-tools"],
    summary="查薪酬分布（脱敏聚合）：仅返回各分组的 min/中位/max 三点与人数，"
    "不返回任何个人明细。by=job_level 按职级切片、by=org 按组织切片。"
    "适合『各职级薪资水平大概什么区间』类问题。",
)
async def comp_distribution(
    by: str = Query("job_level", description="切片维度：job_level/org"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """薪酬分布脱敏聚合"""
    try:
        return await agent_tool_service.comp_distribution(session, by=by)
    except ForbiddenError as exc:
        raise _to_http(exc) from exc


@router.get(
    "/agent-tools/performance-summary",
    response_class=ORJSONResponse,
    tags=["agent-tools"],
    summary="查绩效概览：已收口考核周期的评级分布（S/A/B/C/D 计数）与周期均分"
    "趋势，不列任何个人评级。适合『上个考核周期整体表现如何』类问题。",
)
async def performance_summary(
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """closed 周期绩效概览（聚合口径）"""
    try:
        return await agent_tool_service.performance_summary(session)
    except ForbiddenError as exc:
        raise _to_http(exc) from exc


@router.get(
    "/agent-tools/employee-profile",
    response_class=ORJSONResponse,
    tags=["agent-tools"],
    summary="查员工档案摘要：工号、姓名、组织、岗位、职级、状态（试用/正式等）、"
    "入职/转正日期。证件号与银行卡号不出面，手机号脱敏。需要先拿到员工 ID。",
)
async def employee_profile(
    employee_id: str = Query(..., description="员工 ID"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """员工档案摘要（敏感字段脱敏）"""
    try:
        return await agent_tool_service.employee_profile(session, employee_id)
    except (ForbiddenError, NotFoundError) as exc:
        raise _to_http(exc) from exc
