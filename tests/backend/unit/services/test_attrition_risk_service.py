"""离职风险评分服务单元测试

覆盖：五因子规则加权（薪酬分位/考勤异常/绩效薪酬剪刀差/司龄波动/异动停滞）、
风险分级阈值（≥60 高 / 40-59 中 / <40 低）、零分剔除与倒序、无薪酬权限剔除
薪酬因子、空名单短路、组织下钻展开。
"""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.tenant.context import TenantContext

from hr.services.attrition_risk_service import (
    _risk_level,
    attrition_risk_service,
)


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def scalar_one(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


def _mock_session(execute_results) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock(side_effect=list(execute_results))
    return session


@pytest.fixture(autouse=True)
def _tenant_context():
    TenantContext.set_tenant_id("t-1")
    yield
    TenantContext.clear()


class TestRiskLevel:
    """风险分级阈值"""

    def test_boundaries(self):
        assert _risk_level(60) == "high"
        assert _risk_level(85) == "high"
        assert _risk_level(40) == "mid"
        assert _risk_level(59) == "mid"
        assert _risk_level(39) == "low"
        assert _risk_level(15) == "low"


class TestGetRiskList:
    """离职风险名单"""

    @pytest.mark.asyncio
    async def test_five_factor_scoring_and_ordering(self):
        """高分=薪酬低于带宽下限+考勤异常+司龄波动；停滞因子命中低分；零分剔除。"""
        session = _mock_session(
            execute_results=[
                # 在编员工：e1 波动期低薪、e2 资深有异动、e3 资深无异动
                _FakeResult(
                    rows=[
                        ("e1", "E001", "张三", "org-1", "P5", date(2025, 3, 1)),
                        ("e2", "E002", "李四", "org-2", "P6", date(2020, 1, 1)),
                        ("e3", "E003", "王五", "org-1", "P5", date(2019, 6, 1)),
                    ]
                ),
                # 当期生效定薪总额
                _FakeResult(rows=[("e1", 5000), ("e2", 30000), ("e3", 20000)]),
                # 当前生效薪带
                _FakeResult(
                    rows=[("P5", 8000, 12000, 20000), ("P6", 15000, 20000, 30000)]
                ),
                # 近 90 天考勤异常计数（e1 命中 ≥3）
                _FakeResult(rows=[("e1", 4)]),
                # 最近 closed 周期
                _FakeResult(rows=["cyc-1"]),
                # 周期评级（e3 校准 S，e2 初评 B）
                _FakeResult(rows=[("e3", "S", None), ("e2", None, "B")]),
                # 近 180 天异动（仅 e2）
                _FakeResult(rows=["e2"]),
            ]
        )
        result = await attrition_risk_service.get_risk_list(session)
        assert result.total == 3  # 参评在编人数
        assert [item.employee_id for item in result.items] == ["e1", "e3"]  # e2 零分剔除
        top = result.items[0]
        assert top.score == 65  # 低薪 30 + 考勤 20 + 司龄波动 15
        assert top.level == "high"
        assert top.factors == [
            "薪酬低于职级薪带下限",
            "近90天考勤异常≥3次",
            "司龄处于1-3年波动期",
        ]
        low = result.items[1]
        assert low.score == 15  # 近 180 天无异动且司龄 ≥2 年
        assert low.level == "low"
        assert low.factors == ["近180天无异动且司龄≥2年"]

    @pytest.mark.asyncio
    async def test_no_comp_permission_excludes_comp_factors(self):
        """include_comp=False：不查薪酬/薪带，薪酬与绩效剪刀差因子不参与。"""
        session = _mock_session(
            execute_results=[
                _FakeResult(
                    rows=[
                        ("e1", "E001", "张三", "org-1", "P5", date(2025, 3, 1)),
                    ]
                ),
                _FakeResult(rows=[("e1", 4)]),      # 考勤异常
                _FakeResult(rows=["cyc-1"]),        # closed 周期
                _FakeResult(rows=[("e1", "S", None)]),  # 绩效 S（无薪酬比对不命中）
                _FakeResult(rows=[]),               # 近 180 天异动
            ]
        )
        result = await attrition_risk_service.get_risk_list(
            session, include_comp=False
        )
        assert result.total == 1
        top = result.items[0]
        assert top.score == 35  # 考勤 20 + 司龄波动 15
        assert top.level == "low"  # 35 < 40 未达中风险阈值
        assert all("薪酬" not in factor for factor in top.factors)

    @pytest.mark.asyncio
    async def test_empty_roster_short_circuit(self):
        session = _mock_session(execute_results=[_FakeResult(rows=[])])
        result = await attrition_risk_service.get_risk_list(session)
        assert result.total == 0
        assert result.items == []
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_org_filter_expands_subtree(self):
        session = _mock_session(execute_results=[_FakeResult(rows=[])])
        with patch(
            "hr.services.attrition_risk_service.employee_service.expand_org_ids",
            new=AsyncMock(return_value=["org-1", "org-11"]),
        ) as expand:
            result = await attrition_risk_service.get_risk_list(
                session, org_id="org-1"
            )
        expand.assert_awaited_once_with(session, "org-1")
        assert result.total == 0
