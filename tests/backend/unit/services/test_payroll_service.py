"""发薪批次服务单元测试

覆盖：期间租户唯一与格式校验、试算分段折算（10-15 调薪双区间按天加权）、
月度固定项带出与非固定项不带出、明细修正 draft 门禁与备注必填、
状态机（确认/发放/取消）与锁定语义。
"""

from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openpyxl import load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ConflictError
from framework.tenant.context import TenantContext

from hr.models import (
    Employee,
    EmployeeSalaryPackage,
    PayrollEntry,
    PayrollRun,
    SalaryItem,
)
from hr.schemas.salary import PayrollRunCreate
from hr.services.payroll_service import payroll_service


class _FakeResult:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one(self):
        if self._scalar is not None:
            return self._scalar
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def one(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


def _mock_session(get_map=None, execute_results=None) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    added: list = []
    session.add = MagicMock(side_effect=added.append)
    session._added = added
    session.delete = AsyncMock()

    async def _get(model, pk):
        return (get_map or {}).get((model.__name__, str(pk)))

    session.get = AsyncMock(side_effect=_get)
    session.execute = AsyncMock(
        side_effect=list(execute_results) if execute_results else []
    )
    return session


def _run(**overrides) -> PayrollRun:
    defaults = dict(
        id="run-1", tenant_id="t-1", period="2026-10", status="draft"
    )
    defaults.update(overrides)
    return PayrollRun(**defaults)


def _item(**overrides) -> SalaryItem:
    defaults = dict(
        id="item-1",
        tenant_id="t-1",
        code="base_monthly",
        name="月度基本工资",
        category="base",
        ext_data={"monthly_fixed": True},
        can_edit=True,
        sort=0,
    )
    defaults.update(overrides)
    return SalaryItem(**defaults)


def _employee(**overrides) -> Employee:
    defaults = dict(
        id="emp-1",
        tenant_id="t-1",
        employee_no="EMP0001",
        name="张三",
        status="regular",
    )
    defaults.update(overrides)
    return Employee(**defaults)


def _package(**overrides) -> EmployeeSalaryPackage:
    defaults = dict(
        id="pkg-1",
        tenant_id="t-1",
        employee_id="emp-1",
        item_id="item-1",
        amount=3100.0,
        reason="hire",
        effective_from=date(2026, 1, 1),
        effective_to=None,
    )
    defaults.update(overrides)
    return EmployeeSalaryPackage(**defaults)


@pytest.fixture(autouse=True)
def _tenant_context():
    TenantContext.set_tenant_id("t-1")
    yield
    TenantContext.clear()


class TestCreateRun:
    """创建批次"""

    @pytest.mark.asyncio
    async def test_invalid_period_rejected(self):
        session = _mock_session()
        with pytest.raises(BadRequestError, match="YYYY-MM"):
            await payroll_service.create_run(session, "2026-13")

    @pytest.mark.asyncio
    async def test_duplicate_period_conflict(self):
        session = _mock_session(execute_results=[_FakeResult(rows=[1])])
        with pytest.raises(ConflictError, match="已存在"):
            await payroll_service.create_run(
                session, PayrollRunCreate(period="2026-10").period
            )

    @pytest.mark.asyncio
    async def test_success_submits_task(self):
        session = _mock_session(execute_results=[_FakeResult(rows=[])])
        task = MagicMock()
        task.id = "task-1"
        with patch(
            "framework.tasks.service.task_service.submit", new=AsyncMock(return_value=task)
        ) as submit:
            result = await payroll_service.create_run(session, "2026-10")
        assert result["task_id"] == "task-1"
        assert result["run"].period == "2026-10"
        submit.assert_awaited_once()
        assert submit.await_args.kwargs["task_type"] == "hr_payroll_calc"
        snapshot = submit.await_args.kwargs["config_snapshot"]
        assert snapshot["tenant_id"] == "t-1"


class TestEffectiveSegments:
    """分段折算核心口径"""

    @pytest.mark.asyncio
    async def test_mid_month_adjust_two_segments(self):
        """10-15 调薪 → 10 月批次两区间分段：15 天旧标准 + 16 天新标准。"""
        old = _package(
            id="pkg-old",
            amount=3100.0,
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 10, 15),
        )
        new = _package(
            id="pkg-new",
            amount=6200.0,
            effective_from=date(2026, 10, 16),
            effective_to=None,
        )
        session = _mock_session(execute_results=[_FakeResult(rows=[old, new])])
        segments = await payroll_service._effective_segments(
            session, "emp-1", "item-1", date(2026, 10, 1), date(2026, 10, 31)
        )
        assert len(segments) == 2
        assert segments[0][0] == date(2026, 10, 1)
        assert segments[0][1] == date(2026, 10, 15)
        assert segments[0][2] == Decimal("1500.00")  # 3100 × 15/31
        assert segments[1][0] == date(2026, 10, 16)
        assert segments[1][1] == date(2026, 10, 31)
        assert segments[1][2] == Decimal("3200.00")  # 6200 × 16/31

    @pytest.mark.asyncio
    async def test_single_full_month(self):
        session = _mock_session(execute_results=[_FakeResult(rows=[_package()])])
        segments = await payroll_service._effective_segments(
            session, "emp-1", "item-1", date(2026, 10, 1), date(2026, 10, 31)
        )
        assert len(segments) == 1
        assert segments[0][2] == Decimal("3100.00")

    @pytest.mark.asyncio
    async def test_no_active_package(self):
        future = _package(effective_from=date(2026, 11, 1))
        session = _mock_session(execute_results=[_FakeResult(rows=[future])])
        segments = await payroll_service._effective_segments(
            session, "emp-1", "item-1", date(2026, 10, 1), date(2026, 10, 31)
        )
        assert segments == []


class TestCalculateRun:
    """试算明细生成"""

    @pytest.mark.asyncio
    async def test_fixed_items_only_and_segment_note(self):
        fixed = _item()
        non_fixed = _item(
            id="item-2",
            code="bonus_annual",
            name="年终奖",
            category="bonus",
            ext_data={"monthly_fixed": False},
        )
        old = _package(
            id="pkg-old",
            amount=3100.0,
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 10, 15),
        )
        new = _package(
            id="pkg-new",
            amount=6200.0,
            effective_from=date(2026, 10, 16),
            effective_to=None,
        )
        session = _mock_session(
            get_map={("PayrollRun", "run-1"): _run()},
            execute_results=[
                _FakeResult(rows=[]),                      # 旧明细清空查询
                _FakeResult(rows=[fixed, non_fixed]),      # 启用薪酬项
                _FakeResult(rows=[_employee()]),           # 在职员工
                _FakeResult(rows=[]),                      # 绩效系数映射（无评估）
                _FakeResult(rows=[old, new]),              # item-1 定薪区间
            ],
        )
        run = await payroll_service.calculate_run(session, "run-1")
        assert run.status == "draft"
        entries = [obj for obj in session._added if isinstance(obj, PayrollEntry)]
        assert len(entries) == 1  # 非月度固定项不带出
        assert entries[0].item_code == "base_monthly"
        assert entries[0].amount == Decimal("4700.00")  # 1500 + 3200
        assert entries[0].note is not None
        assert "分段" in entries[0].note

    @pytest.mark.asyncio
    async def test_offboarded_employee_skipped(self):
        """在职过滤发生在查询层（status in probation/regular/intern），mock 返回空集。"""
        fixed = _item()
        session = _mock_session(
            get_map={("PayrollRun", "run-1"): _run()},
            execute_results=[
                _FakeResult(rows=[]),
                _FakeResult(rows=[fixed]),
                _FakeResult(rows=[]),
                _FakeResult(rows=[]),
            ],
        )
        await payroll_service.calculate_run(session, "run-1")
        assert not [o for o in session._added if isinstance(o, PayrollEntry)]

    @pytest.mark.asyncio
    async def test_performance_item_applies_review_coefficient(self):
        """performance 项按最近 closed 周期评估系数放大：6200 × 1.2 = 7440.00。"""
        perf_item = _item(
            id="item-2",
            code="perf_monthly",
            name="月度绩效工资",
            category="performance",
        )
        session = _mock_session(
            get_map={("PayrollRun", "run-1"): _run()},
            execute_results=[
                _FakeResult(rows=[]),                                  # 旧明细清空
                _FakeResult(rows=[perf_item]),                         # 启用薪酬项
                _FakeResult(rows=[_employee()]),                       # 在职员工
                _FakeResult(rows=[("emp-1", Decimal("1.2"))]),         # 绩效系数映射（A→1.2）
                _FakeResult(rows=[_package(item_id="item-2", amount=6200.0)]),  # 定薪区间
            ],
        )
        await payroll_service.calculate_run(session, "run-1")
        entries = [obj for obj in session._added if isinstance(obj, PayrollEntry)]
        assert len(entries) == 1
        assert entries[0].amount == Decimal("7440.00")

    @pytest.mark.asyncio
    async def test_performance_item_without_review_falls_back_to_one(self):
        """无 closed 周期评估的员工 performance 项兜底系数 1.0。"""
        perf_item = _item(
            id="item-2",
            code="perf_monthly",
            name="月度绩效工资",
            category="performance",
        )
        session = _mock_session(
            get_map={("PayrollRun", "run-1"): _run()},
            execute_results=[
                _FakeResult(rows=[]),
                _FakeResult(rows=[perf_item]),
                _FakeResult(rows=[_employee()]),
                _FakeResult(rows=[]),
                _FakeResult(rows=[_package(item_id="item-2", amount=6200.0)]),
            ],
        )
        await payroll_service.calculate_run(session, "run-1")
        entries = [obj for obj in session._added if isinstance(obj, PayrollEntry)]
        assert len(entries) == 1
        assert entries[0].amount == Decimal("6200.00")

    @pytest.mark.asyncio
    async def test_non_draft_rejected(self):
        session = _mock_session(
            get_map={("PayrollRun", "run-1"): _run(status="confirmed")}
        )
        with pytest.raises(ConflictError, match="仅草稿可试算"):
            await payroll_service.calculate_run(session, "run-1")


class TestEntryUpdate:
    """明细人工修正"""

    @pytest.mark.asyncio
    async def test_amount_change_requires_note(self):
        entry = PayrollEntry(
            id="entry-1", tenant_id="t-1", run_id="run-1", employee_id="emp-1",
            item_id="item-1", item_code="base_monthly", amount=4700.0,
        )
        session = _mock_session(
            get_map={
                ("PayrollRun", "run-1"): _run(),
                ("PayrollEntry", "entry-1"): entry,
            }
        )
        with pytest.raises(BadRequestError, match="备注"):
            await payroll_service.update_entry(
                session, "run-1", "entry-1", amount=5000.0, note=None
            )

    @pytest.mark.asyncio
    async def test_confirmed_run_locked(self):
        session = _mock_session(
            get_map={("PayrollRun", "run-1"): _run(status="confirmed")}
        )
        with pytest.raises(ConflictError, match="不可修正"):
            await payroll_service.update_entry(
                session, "run-1", "entry-1", amount=5000.0, note="补发"
            )

    @pytest.mark.asyncio
    async def test_note_update_allowed_without_amount_change(self):
        entry = PayrollEntry(
            id="entry-1", tenant_id="t-1", run_id="run-1", employee_id="emp-1",
            item_id="item-1", item_code="base_monthly", amount=4700.0,
        )
        session = _mock_session(
            get_map={
                ("PayrollRun", "run-1"): _run(),
                ("PayrollEntry", "entry-1"): entry,
            }
        )
        result = await payroll_service.update_entry(
            session, "run-1", "entry-1", amount=4700.0, note="口径说明"
        )
        assert result.note == "口径说明"


class TestRunStateMachine:
    """确认 / 发放 / 取消"""

    @pytest.mark.asyncio
    async def test_confirm_writes_totals(self):
        session = _mock_session(
            get_map={("PayrollRun", "run-1"): _run()},
            execute_results=[_FakeResult(rows=[(Decimal("47000.00"), 10)])],
        )
        run = await payroll_service.confirm_run(session, "run-1")
        assert run.status == "confirmed"
        assert float(run.total_amount) == 47000.00
        assert run.employee_count == 10

    @pytest.mark.asyncio
    async def test_confirm_only_from_draft(self):
        session = _mock_session(
            get_map={("PayrollRun", "run-1"): _run(status="paid")}
        )
        with pytest.raises(ConflictError, match="不可确认"):
            await payroll_service.confirm_run(session, "run-1")

    @pytest.mark.asyncio
    async def test_pay_sets_pay_date(self):
        session = _mock_session(
            get_map={("PayrollRun", "run-1"): _run(status="confirmed")}
        )
        run = await payroll_service.pay_run(session, "run-1")
        assert run.status == "paid"
        assert run.pay_date == date.today()

    @pytest.mark.asyncio
    async def test_paid_cannot_cancel(self):
        session = _mock_session(
            get_map={("PayrollRun", "run-1"): _run(status="paid")}
        )
        with pytest.raises(ConflictError, match="不可取消"):
            await payroll_service.cancel_run(session, "run-1")

    @pytest.mark.asyncio
    async def test_cancel_from_confirmed(self):
        session = _mock_session(
            get_map={("PayrollRun", "run-1"): _run(status="confirmed")}
        )
        run = await payroll_service.cancel_run(session, "run-1")
        assert run.status == "cancelled"


class TestExportRun:
    """标准代发文件导出"""

    @pytest.mark.asyncio
    async def test_draft_rejected(self):
        session = _mock_session(get_map={("PayrollRun", "run-1"): _run(status="draft")})
        with pytest.raises(ConflictError, match="仅确认/已发放批次可导出"):
            await payroll_service.export_run(session, "run-1")

    @pytest.mark.asyncio
    async def test_rows_aggregate_gross_net_and_ordering(self):
        from hr.services.employee_service import EmployeeService

        session = _mock_session(get_map={("PayrollRun", "run-1"): _run(status="confirmed")})
        session.execute = AsyncMock(
            return_value=_FakeResult(
                rows=[
                    ("emp-2", "EMP0002", "李四", "enc-id-2", "enc-bank-2", "建设银行", "base", Decimal("5000.00")),
                    ("emp-1", "EMP0001", "张三", "enc-id-1", "enc-bank-1", "工商银行", "base", Decimal("8000.00")),
                    ("emp-1", "EMP0001", "张三", "enc-id-1", "enc-bank-1", "工商银行", "deduction", Decimal("500.00")),
                ]
            )
        )
        with patch.object(
            EmployeeService,
            "_decrypt_sensitive",
            staticmethod(lambda cipher, label: f"plain({cipher})"),
        ):
            filename, content = await payroll_service.export_run(session, "run-1")

        assert filename == "标准代发-2026-10.xlsx"
        sheet = load_workbook(BytesIO(content)).active
        rows = list(sheet.iter_rows(values_only=True))
        assert rows[0] == ("工号", "姓名", "证件号", "开户行", "银行卡号", "应发", "实发", "期间")
        assert len(rows) == 3
        first, second = rows[1], rows[2]
        # 按工号排序：张三在前；实发 = 应发 8000 - 扣减 500
        assert first == ("EMP0001", "张三", "plain(enc-id-1)", "工商银行", "plain(enc-bank-1)", 8000.0, 7500.0, "2026-10")
        assert second[0] == "EMP0002"
        assert second[6] == 5000.0
