"""hr agent 工具面服务（inner，X-Tenant-Id fail-closed）

四件只读工具：组织编制概览 / 候选人检索（脱敏）/ 招聘漏斗 / 员工档案摘要
（敏感字段不出面）。消费链路对齐 ontology：ai 接口库 OpenAPI 导入 →
tool-bus 装配 → HTTP GET 本面（X-Tenant-Id 回传）。
"""

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.ctx import get_tenant_id
from framework.common.exceptions import BadRequestError, ForbiddenError, NotFoundError

from hr.models import Candidate, CandidateApplication, Employee, Position
from hr.services.requisition_service import requisition_service

_CANDIDATE_LIMIT_MAX = 20


class AgentToolService:
    """智能体工具只读查询（租户过滤由 X-Tenant-Id 上下文自动生效）"""

    @staticmethod
    def _require_tenant() -> str:
        tenant_id = get_tenant_id()
        if not tenant_id:
            raise ForbiddenError("缺少 X-Tenant-Id 头（agent 工具面 fail-closed）")
        return tenant_id

    # ── 组织编制与在编概览 ──

    async def headcount(
        self, session: AsyncSession, org_id: str | None = None
    ) -> dict:
        """编制（生效岗位 headcount 合计）与在编（probation+regular）概览。

        org_id 给定时含子组织（复用员工域组织树展开口径）。
        """
        self._require_tenant()
        org_ids: list[str] | None = None
        if org_id:
            from hr.services.employee_service import employee_service

            org_ids = await employee_service.expand_org_ids(session, org_id)

        headcount_stmt = select(
            func.coalesce(func.sum(Position.headcount), 0)
        ).where(Position.status == "active")
        active_stmt = (
            select(func.count(Employee.id)).where(
                Employee.status.in_(["probation", "regular"])
            )
        )
        if org_ids is not None:
            headcount_stmt = headcount_stmt.where(Position.org_id.in_(org_ids))
            active_stmt = active_stmt.where(Employee.org_id.in_(org_ids))

        headcount_total = (await session.execute(headcount_stmt)).scalar_one()
        active_count = (await session.execute(active_stmt)).scalar_one()
        return {
            "org_id": org_id,
            "headcount": int(headcount_total),
            "active_employees": int(active_count),
            "vacancy": int(headcount_total) - int(active_count),
        }

    # ── 候选人检索（脱敏口径）──

    async def search_candidates(
        self,
        session: AsyncSession,
        *,
        q: str | None = None,
        stage: str | None = None,
        limit: int = 10,
    ) -> dict:
        """候选人检索：姓名/手机号/邮箱匹配；stage 过滤「存在该阶段投递」的候选人。

        手机号与邮箱一律脱敏出站（agent 面不带明文联系方式）。
        """
        self._require_tenant()
        limit = max(1, min(limit, _CANDIDATE_LIMIT_MAX))

        stmt = select(Candidate).order_by(Candidate.created_at.desc()).limit(limit)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                or_(
                    Candidate.name.ilike(like),
                    Candidate.phone.ilike(like),
                    Candidate.email.ilike(like),
                )
            )
        if stage:
            stmt = stmt.where(
                exists(
                    select(CandidateApplication.id).where(
                        CandidateApplication.candidate_id == Candidate.id,
                        CandidateApplication.stage == stage,
                    )
                )
            )

        rows = (await session.execute(stmt)).scalars().all()
        return {
            "count": len(rows),
            "items": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "phone_masked": _mask_phone(c.phone),
                    "email_masked": _mask_email(c.email),
                    "source_channel": c.source_channel,
                    "is_blacklist": bool(c.is_blacklist),
                }
                for c in rows
            ],
        }

    # ── 招聘漏斗统计 ──

    async def recruiting_funnel(
        self, session: AsyncSession, requisition_id: str | None = None
    ) -> dict:
        """招聘漏斗十阶段计数（requisition_id 缺省全租户口径）。"""
        self._require_tenant()
        funnel = await requisition_service.get_funnel(session, requisition_id)
        result: dict = {
            "requisition_id": funnel.requisition_id,
            "stats": [s.model_dump() for s in funnel.stats],
        }
        if requisition_id:
            requisition = await requisition_service.get_requisition(
                session, requisition_id
            )
            result["requisition_title"] = requisition.title
        return result

    # ── 离职率序列（三期扩面）──

    async def turnover_stats(
        self, session: AsyncSession, months: int = 6
    ) -> dict:
        """近 N 月离职率序列：当月离职人数/平均在编/百分数比率（报表同源口径）。"""
        self._require_tenant()
        from hr.services.report_service import report_service

        months = max(1, min(months, 12))
        response = await report_service.get_turnover(session, months=months)
        return {
            "months": months,
            "points": [point.model_dump() for point in response.points],
        }

    # ── 薪酬分布（脱敏聚合）──

    async def comp_distribution(
        self, session: AsyncSession, by: str = "job_level"
    ) -> dict:
        """薪酬分布脱敏聚合：仅 min/median/max 三点，不返回个人明细。

        by=job_level 按职级切片；by=org 按组织切片。
        """
        self._require_tenant()
        from hr.services.report_service import report_service

        if by not in ("job_level", "org"):
            raise BadRequestError("by 仅支持 job_level/org")
        response = await report_service.get_comp_distribution(session)
        items = (
            response.by_level
            if by == "job_level"
            else response.by_org
        )
        return {
            "by": by,
            "items": [
                {
                    "key": item.key,
                    "count": item.count,
                    "min_amount": item.min_amount,
                    "mid_amount": item.mid_amount,
                    "max_amount": item.max_amount,
                }
                for item in items
            ],
        }

    # ── 绩效概览（closed 周期聚合）──

    async def performance_summary(self, session: AsyncSession) -> dict:
        """绩效概览：closed 周期评级分布与均分趋势，不列个人评级。"""
        self._require_tenant()
        from hr.services.report_service import report_service

        response = await report_service.get_performance(session)
        return {
            "cycles": [cycle.model_dump() for cycle in response.cycles],
        }

    # ── 员工档案摘要（敏感字段脱敏）──

    async def employee_profile(self, session: AsyncSession, employee_id: str) -> dict:
        """员工档案摘要：基本信息 + 组织/岗位/职级/状态/关键日期。

        证件号与银行卡号（密文字段）不出面，手机号脱敏。
        """
        self._require_tenant()
        employee = await session.get(Employee, employee_id)
        if not employee:
            raise NotFoundError(f"员工 {employee_id} 不存在")
        return {
            "id": str(employee.id),
            "employee_no": employee.employee_no,
            "name": employee.name,
            "gender": employee.gender,
            "phone_masked": _mask_phone(employee.phone),
            "work_email": employee.work_email,
            "org_id": employee.org_id,
            "position_id": employee.position_id,
            "job_level": employee.job_level,
            "status": employee.status,
            "hire_date": employee.hire_date,
            "regular_date": employee.regular_date,
        }


def _mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    if len(phone) <= 7:
        return phone[:2] + "****"
    return f"{phone[:3]}****{phone[-4:]}"


def _mask_email(email: str | None) -> str | None:
    if not email:
        return None
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    head = local[:1] if local else "*"
    return f"{head}***@{domain}"


agent_tool_service = AgentToolService()
