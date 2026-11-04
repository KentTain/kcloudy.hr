"""报表分析控制器（人事仪表盘 / 离职率 / 招聘漏斗 / 薪酬分布 / 绩效分布 / 离职风险 / 导出）"""

import base64
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from framework.clients.iam_client import get_iam_client
from framework.common.exceptions import ForbiddenError
from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, optional_permission, require_permission

from hr.schemas.report import ReportAskRequest
from hr.services import report_export_service
from hr.services.attrition_risk_service import attrition_risk_service
from hr.services.nl_query_service import nl_query_service
from hr.services.report_service import report_service

router = APIRouter()


@router.get("/reports/overview")
async def get_overview(
    date_from: date | None = None,
    date_to: date | None = None,
    org_id: str | None = None,
    months: int = 6,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:report:read")),
):
    result = await report_service.get_overview(
        session,
        date_from=date_from,
        date_to=date_to,
        org_id=org_id,
        months=months,
    )
    return ApiResponse.success(data=result)


@router.get("/reports/turnover")
async def get_turnover(
    date_from: date | None = None,
    date_to: date | None = None,
    org_id: str | None = None,
    months: int = 6,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:report:read")),
):
    result = await report_service.get_turnover(
        session,
        date_from=date_from,
        date_to=date_to,
        org_id=org_id,
        months=months,
    )
    return ApiResponse.success(data=result)


@router.get("/reports/recruiting")
async def get_recruiting_report(
    date_from: date | None = None,
    date_to: date | None = None,
    org_id: str | None = None,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:report:read")),
):
    result = await report_service.get_recruiting(
        session, date_from=date_from, date_to=date_to, org_id=org_id
    )
    return ApiResponse.success(data=result)


@router.get("/reports/comp-dist")
async def get_comp_distribution(
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:salary_package:read")),
):
    result = await report_service.get_comp_distribution(session)
    return ApiResponse.success(data=result)


@router.get("/reports/performance")
async def get_performance_report(
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:report:read")),
):
    result = await report_service.get_performance(session)
    return ApiResponse.success(data=result)


@router.get("/reports/attrition-risk")
async def get_attrition_risk(
    org_id: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    can_comp: bool = Depends(optional_permission("hr:salary_package:read")),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:report:read")),
):
    """离职风险名单（规则加权评分实时计算；无薪酬权限查看者剔除薪酬因子）"""
    result = await attrition_risk_service.get_risk_list(
        session, org_id=org_id, limit=limit, include_comp=can_comp
    )
    return ApiResponse.success(data=result)


@router.post("/reports/ask")
async def ask_report(
    data: ReportAskRequest,
    can_comp: bool = Depends(optional_permission("hr:salary_package:read")),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:report:read")),
):
    """NL 问数（白名单指标聚合口径；薪酬域无权限时回答注明跳过）"""
    result = await nl_query_service.ask(session, data.question, can_salary=can_comp)
    return ApiResponse.success(data=result)


@router.get("/reports/export")
async def export_report(
    domain: str,
    date_from: date | None = None,
    date_to: date | None = None,
    org_id: str | None = None,
    months: int = 6,
    user_id: str = Depends(get_current_user_id),
    can_salary: bool = Depends(optional_permission("hr:salary_package:read")),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:report:export")),
):
    """报表 Excel 导出（六域；comp-dist 域叠加 hr:salary_package:read；写审计）"""
    if domain == "comp-dist" and not can_salary:
        raise ForbiddenError("薪酬分布导出需薪酬查看权限")
    filename, content = await report_export_service.build_export(
        session,
        domain=domain,
        date_from=date_from,
        date_to=date_to,
        org_id=org_id,
        months=months,
        include_comp=can_salary,
    )
    await get_iam_client().create_audit_log(
        session,
        business_domain="hr",
        operation_type="export",
        resource_type="report",
        resource_name=f"报表导出 {domain}",
        detail={
            "operator_id": user_id,
            "domain": domain,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "org_id": org_id,
        },
    )
    return ApiResponse.success(
        data={"filename": filename, "content_base64": base64.b64encode(content).decode()}
    )
