"""招聘渠道归集流集成测试（§8.2）：发布 → 拉取归集（provider 假桩语义直调
归一入口）→ 幂等 → 漏斗推进 → 漏斗统计。

真库直跑（hr schema），事务内断言不 commit（回滚零清理）；iam 取号为外部
依赖（编码规则种子不随探针租户下发），按单测先例类级替换 generate_code。
"""

from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from framework.clients.iam_client import IamClient
from framework.tenant.context import TenantContext
from hr.models.recruiting import CandidateApplication, JobPosting, JobRequisition
from hr.schemas.recruiting import RequisitionCreate
from hr.services.candidate_service import candidate_service
from hr.services.requisition_service import requisition_service

pytestmark = pytest.mark.integration

TENANT = "itest-hr-recruit"


@pytest_asyncio.fixture()
async def session(postgres_engine, monkeypatch) -> AsyncIterator[AsyncSession]:
    from framework.database.events.tenant import register_tenant_events
    from framework.database.interceptors.query import register_tenant_auto_filter

    register_tenant_auto_filter()
    register_tenant_events()
    TenantContext.set_tenant_id(TENANT)

    async def fake_generate_code(self, sess, tenant_id, code, field_values=None, count=1):
        return "REQ-ITEST-0001"

    monkeypatch.setattr(IamClient, "generate_code", fake_generate_code)

    maker = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with maker() as sess:
        yield sess
        await sess.rollback()
    TenantContext.clear()


@pytest.mark.asyncio
async def test_publish_collect_and_funnel_flow(session: AsyncSession):
    """internal 发布即 published；归一入口建档建投递；幂等复用；漏斗推进与统计"""
    requisition = await requisition_service.create_requisition(
        session,
        RequisitionCreate(title="集成探针岗位", org_id="itest-org", headcount=1, channels=["internal"]),
    )
    assert requisition.status == "recruiting"

    postings = (
        await session.execute(select(JobPosting).where(JobPosting.requisition_id == requisition.id))
    ).scalars().all()
    assert len(postings) == 1
    assert postings[0].channel == "internal"
    assert postings[0].status == "published"

    # 拉取/webhook 共同归一入口：首次新建（待初筛）
    application, suggestion, created = await candidate_service.collect_application(
        session,
        channel="internal",
        external_candidate_id="ext-cand-1",
        external_application_id="ext-app-1",
        requisition_id=str(requisition.id),
        name="探针候选人",
        phone="13800000001",
    )
    assert created is True
    assert application.stage == "pending_screening"

    # 幂等：同渠道同外部候选人同需求重复归集 → 复用既有投递不重投
    again, _, created_again = await candidate_service.collect_application(
        session,
        channel="internal",
        external_candidate_id="ext-cand-1",
        external_application_id="ext-app-1",
        requisition_id=str(requisition.id),
        name="探针候选人",
        phone="13800000001",
    )
    assert created_again is False
    assert str(again.id) == str(application.id)

    # 漏斗推进：合法链路流转
    await candidate_service.change_stage(session, str(application.id), "screening_passed", remark="初筛通过")
    await candidate_service.change_stage(session, str(application.id), "interviewing", remark="约面")

    # 非法流转被状态机拦截
    with pytest.raises(Exception, match="不允许流转"):
        await candidate_service.change_stage(session, str(application.id), "onboarded")

    funnel = await requisition_service.get_funnel(session, str(requisition.id))
    counts = {stat.stage: stat.count for stat in funnel.stats}
    assert counts["interviewing"] == 1
    assert counts["pending_screening"] == 0
    assert counts["onboarded"] == 0


@pytest.mark.asyncio
async def test_collect_suggestion_when_phone_matches_existing(session: AsyncSession):
    """手机号命中既有其他候选人 → 返回合并建议（不自动合并）"""
    requisition = await requisition_service.create_requisition(
        session, RequisitionCreate(title="合并建议探针", org_id="itest-org", headcount=1)
    )
    first, _, _ = await candidate_service.collect_application(
        session,
        channel="internal",
        external_candidate_id="ext-cand-a",
        external_application_id=None,
        requisition_id=str(requisition.id),
        name="候选人A",
        phone="13900000001",
    )
    _, suggestion, created = await candidate_service.collect_application(
        session,
        channel="internal",
        external_candidate_id="ext-cand-b",
        external_application_id=None,
        requisition_id=str(requisition.id),
        name="候选人B",
        phone="13900000001",
    )
    assert created is True
    # 合并建议：新候选人(candidate_id=B) 撞既有档(target_id=A)，按手机号命中
    assert suggestion["matched_by"] == "phone"
    assert suggestion["target_id"] == str(first.candidate_id)
    assert suggestion["candidate_id"] != suggestion["target_id"]

    apps = (
        await session.execute(
            select(CandidateApplication).where(CandidateApplication.requisition_id == requisition.id)
        )
    ).scalars().all()
    assert len(apps) == 2
