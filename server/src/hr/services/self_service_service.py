"""员工自助服务：console 本人数据（user_id 定位）+ 经理团队视角

本人薪酬单仅由已发放（paid）批次生成；团队成员不含薪酬明细。
目标/绩效/变更申请仅本人可见；团队台数据按归属（组织子树/面试官/评估人）裁剪。
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)

from hr.models import (
    Candidate,
    CandidateApplication,
    Employee,
    Interview,
    JobRequisition,
    PayrollEntry,
    PayrollRun,
    PerfCycle,
    PerfGoal,
    PerfReview,
)
from hr.schemas.employee import EmployeeResponse
from hr.schemas.recruiting import RequisitionResponse
from hr.services.approval_service import approval_service
from hr.services.employee_service import employee_service
from hr.services.eav_service import eav_service
from hr.services.perf_review_service import perf_review_service


class SelfServiceService:
    """员工自助（ESS）业务：仅本人与所辖组织数据"""

    async def get_profile(self, session: AsyncSession, user_id: str) -> dict:
        employee = await employee_service.get_employee_by_user_id(session, user_id)
        detail = await employee_service.get_employee_detail(session, str(employee.id))
        attributes = await eav_service.get_employee_attributes(
            session, str(employee.id)
        )
        return {"profile": detail, "attributes": attributes}

    # ── 我的薪酬单 ──

    async def list_pay_slips(self, session: AsyncSession, user_id: str) -> list[dict]:
        employee = await employee_service.get_employee_by_user_id(session, user_id)
        rows = (
            await session.execute(
                select(
                    PayrollRun.id,
                    PayrollRun.period,
                    PayrollRun.pay_date,
                    func.count(PayrollEntry.id),
                    func.sum(PayrollEntry.amount),
                )
                .join(PayrollRun, PayrollEntry.run_id == PayrollRun.id)
                .where(
                    PayrollEntry.employee_id == employee.id,
                    PayrollRun.status == "paid",
                )
                .group_by(PayrollRun.id, PayrollRun.period, PayrollRun.pay_date)
                .order_by(PayrollRun.period.desc())
            )
        ).all()
        return [
            {
                "period": period,
                "pay_date": pay_date,
                "item_count": item_count,
                "total_amount": round(float(total), 2) if total is not None else 0.0,
            }
            for _run_id, period, pay_date, item_count, total in rows
        ]

    async def get_pay_slip(
        self, session: AsyncSession, user_id: str, period: str
    ) -> dict:
        employee = await employee_service.get_employee_by_user_id(session, user_id)
        run = (
            await session.execute(
                select(PayrollRun)
                .where(PayrollRun.period == period, PayrollRun.status == "paid")
                .limit(1)
            )
        ).scalar_one_or_none()
        if not run:
            raise NotFoundError(f"期间 {period} 无已发放薪酬单")

        entries = (
            await session.execute(
                select(PayrollEntry)
                .where(
                    PayrollEntry.run_id == run.id,
                    PayrollEntry.employee_id == employee.id,
                )
                .order_by(PayrollEntry.item_code)
            )
        ).scalars().all()
        total = sum(float(entry.amount) for entry in entries)
        return {
            "period": run.period,
            "pay_date": run.pay_date,
            "total_amount": round(total, 2),
            "items": [
                {
                    "item_code": entry.item_code,
                    "amount": float(entry.amount),
                    "note": entry.note,
                }
                for entry in entries
            ],
        }

    # ── 团队成员（经理视角）──

    async def list_team_employees(
        self,
        session: AsyncSession,
        user_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        employee = await employee_service.get_employee_by_user_id(session, user_id)
        led_org_ids = await self._led_org_ids(session, user_id)
        if not led_org_ids:
            return {"total": 0, "items": []}
        org_ids: set[str] = set()
        for org_id in led_org_ids:
            org_ids.update(await employee_service.expand_org_ids(session, org_id))

        conditions = [Employee.org_id.in_(org_ids), Employee.status != "offboarded"]
        total = (
            await session.execute(
                select(func.count(Employee.id)).where(*conditions)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(Employee)
                .where(*conditions)
                .order_by(Employee.employee_no)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return {
            "total": total,
            "items": [EmployeeResponse.model_validate(item) for item in rows],
        }

    async def _led_org_ids(self, session: AsyncSession, user_id: str) -> list[str]:
        """用户担任负责人的组织（is_leader 权威源：iam.user_organizations）"""
        from iam.models import UserOrganization

        stmt = select(UserOrganization.organization_id).where(
            UserOrganization.user_id == user_id,
            UserOrganization.is_leader.is_(True),
        )
        return [row[0] for row in (await session.execute(stmt)).all()]

    # ── 我的目标 ──

    async def list_my_goals(self, session: AsyncSession, user_id: str) -> list[dict]:
        employee = await employee_service.get_employee_by_user_id(session, user_id)
        rows = (
            await session.execute(
                select(PerfGoal, PerfCycle)
                .join(PerfCycle, PerfGoal.cycle_id == PerfCycle.id)
                .where(PerfGoal.employee_id == employee.id)
                .order_by(PerfCycle.start_date.desc(), PerfGoal.code)
            )
        ).all()
        groups: dict[str, dict] = {}
        for goal, cycle in rows:
            key = str(cycle.id)
            if key not in groups:
                groups[key] = {
                    "cycle_id": str(cycle.id),
                    "cycle_name": cycle.name,
                    "cycle_status": cycle.status,
                    "start_date": cycle.start_date,
                    "end_date": cycle.end_date,
                    "goals": [],
                }
            groups[key]["goals"].append(
                {
                    "id": str(goal.id),
                    "code": goal.code,
                    "name": goal.name,
                    "weight": float(goal.weight),
                    "target_value": goal.target_value,
                    "actual_value": goal.actual_value,
                    "progress": goal.progress,
                    "status": goal.status,
                }
            )
        return sorted(groups.values(), key=lambda g: g["cycle_status"] != "active")

    async def update_my_goal_progress(
        self,
        session: AsyncSession,
        user_id: str,
        goal_id: str,
        *,
        progress: int,
        actual_value: str | None = None,
    ) -> PerfGoal:
        employee = await employee_service.get_employee_by_user_id(session, user_id)
        goal = await session.get(PerfGoal, goal_id)
        if not goal or str(goal.employee_id) != str(employee.id):
            raise ForbiddenError("仅可更新本人目标进度")
        cycle = await session.get(PerfCycle, goal.cycle_id)
        if not cycle or cycle.status != "active":
            raise ConflictError(
                f"周期状态为 {getattr(cycle, 'status', None)}，仅进行中（active）周期可更新目标进度"
            )
        if not 0 <= progress <= 100:
            raise BadRequestError("进度须在 0-100 之间")
        goal.progress = progress
        if actual_value is not None:
            goal.actual_value = actual_value
        await session.flush()
        return goal

    # ── 我的绩效 ──

    async def list_my_reviews(self, session: AsyncSession, user_id: str) -> list[dict]:
        employee = await employee_service.get_employee_by_user_id(session, user_id)
        rows = (
            await session.execute(
                select(PerfReview, PerfCycle)
                .join(PerfCycle, PerfReview.cycle_id == PerfCycle.id)
                .where(PerfReview.employee_id == employee.id)
                .order_by(PerfCycle.start_date.desc(), PerfReview.created_at.desc())
            )
        ).all()
        return [
            {
                "id": str(review.id),
                "cycle_id": str(cycle.id),
                "cycle_name": cycle.name,
                "cycle_status": cycle.status,
                "status": review.status,
                "self_score": review.self_score,
                "score": review.score,
                "rating": review.rating,
                "final_rating": review.calibrated_rating or review.rating,
                # 未收口周期不展示系数
                "coefficient": (
                    float(review.coefficient)
                    if cycle.status == "closed" and review.coefficient is not None
                    else None
                ),
            }
            for review, cycle in rows
        ]

    # ── 档案变更申请（走统一审批流） ──

    async def submit_change_request(
        self, session: AsyncSession, user_id: str, *, title: str, changes: list[dict]
    ) -> dict:
        employee = await employee_service.get_employee_by_user_id(session, user_id)
        request = await approval_service.submit(
            session,
            biz_type="profile_change",
            applicant_employee_id=str(employee.id),
            applicant_user_id=user_id,
            title=title,
            payload={"changes": changes},
        )
        return {"id": str(request.id), "status": request.status}

    async def list_my_change_requests(
        self, session: AsyncSession, user_id: str, *, page: int = 1, page_size: int = 20
    ) -> dict:
        employee = await employee_service.get_employee_by_user_id(session, user_id)
        return await approval_service.list_requests(
            session,
            biz_type="profile_change",
            applicant_employee_id=str(employee.id),
            page=page,
            page_size=page_size,
        )

    async def cancel_change_request(
        self, session: AsyncSession, user_id: str, request_id: str
    ) -> None:
        employee = await employee_service.get_employee_by_user_id(session, user_id)
        await approval_service.cancel(
            session, request_id, operator_employee_id=str(employee.id)
        )

    # ── 团队工作台（经理视角） ──

    async def list_team_requisitions(
        self, session: AsyncSession, user_id: str, *, page: int = 1, page_size: int = 20
    ) -> dict:
        employee = await employee_service.get_employee_by_user_id(session, user_id)
        if not employee.org_id:
            return {"total": 0, "items": []}
        org_ids = await employee_service.expand_org_ids(session, str(employee.org_id))
        conditions = [JobRequisition.org_id.in_(org_ids)]
        total = (
            await session.execute(
                select(func.count(JobRequisition.id)).where(*conditions)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(JobRequisition)
                .where(*conditions)
                .order_by(JobRequisition.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return {
            "total": total,
            "items": [RequisitionResponse.model_validate(item) for item in rows],
        }

    async def list_team_interviews(self, session: AsyncSession, user_id: str) -> list[dict]:
        employee = await employee_service.get_employee_by_user_id(session, user_id)
        rows = (
            await session.execute(
                select(Interview, JobRequisition, Candidate)
                .join(CandidateApplication, Interview.application_id == CandidateApplication.id)
                .join(JobRequisition, CandidateApplication.requisition_id == JobRequisition.id)
                .join(Candidate, CandidateApplication.candidate_id == Candidate.id)
                .where(Interview.interviewer_id == employee.id)
                .order_by(Interview.scheduled_at.desc())
            )
        ).all()
        return [
            {
                "id": str(interview.id),
                "round": interview.round,
                "scheduled_at": interview.scheduled_at,
                "interview_form": interview.interview_form,
                "result": interview.result,
                "candidate_name": candidate.name,
                "requisition_id": str(requisition.id),
                "requisition_title": requisition.title,
            }
            for interview, requisition, candidate in rows
        ]

    async def list_team_reviews(self, session: AsyncSession, user_id: str) -> list[dict]:
        employee = await employee_service.get_employee_by_user_id(session, user_id)
        rows = (
            await session.execute(
                select(PerfReview, PerfCycle)
                .join(PerfCycle, PerfReview.cycle_id == PerfCycle.id)
                .where(
                    PerfReview.reviewer_employee_id == employee.id,
                    PerfCycle.status == "scoring",
                    PerfReview.status == "pending",
                )
                .order_by(PerfReview.created_at.asc())
            )
        ).all()
        if not rows:
            return []

        employee_ids = {str(review.employee_id) for review, _ in rows}
        employees = {
            str(item.id): item
            for item in (
                await session.execute(select(Employee).where(Employee.id.in_(employee_ids)))
            ).scalars().all()
        }
        # 目标达成摘要：按（周期×员工）分组聚合加权进度
        stat_rows = (
            await session.execute(
                select(
                    PerfGoal.cycle_id,
                    PerfGoal.employee_id,
                    func.count(PerfGoal.id),
                    func.coalesce(func.sum(PerfGoal.weight * PerfGoal.progress), 0),
                )
                .where(
                    PerfGoal.cycle_id.in_({str(review.cycle_id) for review, _ in rows}),
                    PerfGoal.employee_id.in_(employee_ids),
                )
                .group_by(PerfGoal.cycle_id, PerfGoal.employee_id)
            )
        ).all()
        stats = {
            (str(cycle_id), str(employee_id)): (int(count), Decimal(str(weighted)))
            for cycle_id, employee_id, count, weighted in stat_rows
        }
        items = []
        for review, cycle in rows:
            employee_item = employees.get(str(review.employee_id))
            count, weighted = stats.get(
                (str(cycle.id), str(review.employee_id)), (0, Decimal("0"))
            )
            items.append(
                {
                    "id": str(review.id),
                    "cycle_id": str(cycle.id),
                    "cycle_name": cycle.name,
                    "employee_no": employee_item.employee_no if employee_item else None,
                    "employee_name": employee_item.name if employee_item else None,
                    "goal_count": count,
                    "weighted_progress": round(float(weighted) / 100, 1),
                    "self_score": review.self_score,
                }
            )
        return items

    async def submit_team_review_score(
        self,
        session: AsyncSession,
        user_id: str,
        review_id: str,
        *,
        score: Decimal,
        rating: str,
        self_score: Decimal | None = None,
    ) -> dict:
        employee = await employee_service.get_employee_by_user_id(session, user_id)
        review = await session.get(PerfReview, review_id)
        if not review or str(review.reviewer_employee_id) != str(employee.id):
            raise ForbiddenError("仅可对本人担任评估人的评估提交评分")
        updated = await perf_review_service.submit_score(
            session, review_id, score=score, rating=rating, self_score=self_score
        )
        employee_item = await session.get(Employee, updated.employee_id)
        cycle = await session.get(PerfCycle, updated.cycle_id)
        return perf_review_service.to_response(
            updated, employee=employee_item, cycle_status=cycle.status if cycle else None
        )


self_service_service = SelfServiceService()
