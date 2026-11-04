"""发薪批次服务：批次状态机 / 试算（月度固定项 + 调薪分段折算）/ 明细修正 / 确认发放 / 标准代发导出"""

import calendar
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO

from loguru import logger
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.ctx import get_tenant_id
from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError

from hr.models import (
    Employee,
    EmployeeSalaryPackage,
    PayrollEntry,
    PayrollRun,
    PerfCycle,
    PerfReview,
    SalaryItem,
)
from hr.schemas.salary import (
    PayrollEntryResponse,
    PayrollRunResponse,
)

_logger = logger.bind(name=__name__)

_PERIOD_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

_PAYROLL_TASK_TYPE = "hr_payroll_calc"
_PAYROLL_QUEUE = "hr-payroll"

_PAYROLL_EMPLOYEE_STATUSES = ("probation", "regular", "intern")

# 绩效系数缺省值（员工无最近 closed 周期评估时兜底）
_PERF_COEFFICIENT = Decimal("1.0")

_TWO_PLACES = Decimal("0.01")


class PayrollService:
    """发薪批次业务（金额一律元 DECIMAL(12,2)，无浮点裸算）"""

    # ── 批次 CRUD / 状态机 ──

    async def create_run(self, session: AsyncSession, period: str) -> dict:
        """创建批次（期间租户唯一）+ 提交异步试算任务。"""
        if not _PERIOD_PATTERN.match(period):
            raise BadRequestError("期间格式须为 YYYY-MM")
        existing = (
            await session.execute(
                select(PayrollRun.id).where(PayrollRun.period == period).limit(1)
            )
        ).scalar_one_or_none()
        if existing:
            raise ConflictError(f"{period} 期间批次已存在")

        run = PayrollRun(tenant_id=get_tenant_id(), period=period, status="draft")
        session.add(run)
        await session.flush()

        from framework.tasks.service import task_service

        task = await task_service.submit(
            session,
            task_type=_PAYROLL_TASK_TYPE,
            queue=_PAYROLL_QUEUE,
            config_snapshot={"run_id": str(run.id), "tenant_id": get_tenant_id()},
            resource_type="hr_payroll_run",
            resource_id=str(run.id),
        )
        return {"run": run, "task_id": str(task.id)}

    async def list_runs(
        self,
        session: AsyncSession,
        *,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        conditions = []
        if status:
            conditions.append(PayrollRun.status == status)
        total = (
            await session.execute(
                select(func.count(PayrollRun.id)).where(*conditions)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(PayrollRun)
                .where(*conditions)
                .order_by(PayrollRun.period.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        items = rows.scalars().all()
        return {
            "total": total,
            "items": [self.to_run_response(run) for run in items],
        }

    async def get_run(self, session: AsyncSession, run_id: str) -> PayrollRun:
        run = await session.get(PayrollRun, run_id)
        if not run:
            raise NotFoundError(f"发薪批次 {run_id} 不存在")
        return run

    async def list_entries(
        self,
        session: AsyncSession,
        run_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> dict:
        await self.get_run(session, run_id)
        conditions = [PayrollEntry.run_id == run_id]
        total = (
            await session.execute(
                select(func.count(PayrollEntry.id)).where(*conditions)
            )
        ).scalar_one()
        rows = (
            await session.execute(
                select(PayrollEntry, Employee)
                .join(Employee, PayrollEntry.employee_id == Employee.id)
                .where(*conditions)
                .order_by(Employee.employee_no, PayrollEntry.item_code)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return {
            "total": total,
            "items": [
                self.to_entry_response(entry, employee)
                for entry, employee in rows
            ],
        }

    async def update_entry(
        self,
        session: AsyncSession,
        run_id: str,
        entry_id: str,
        *,
        amount: float,
        note: str | None = None,
    ) -> PayrollEntry:
        """明细人工修正（仅 draft 态；金额修改须填写补发/扣减原因）。"""
        run = await self.get_run(session, run_id)
        if run.status != "draft":
            raise ConflictError(f"批次状态为 {run.status}，明细不可修正")
        entry = await session.get(PayrollEntry, entry_id)
        if not entry or str(entry.run_id) != run_id:
            raise NotFoundError(f"发薪明细 {entry_id} 不存在")
        new_amount = Decimal(str(amount)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        if new_amount != entry.amount and not (note or "").strip():
            raise BadRequestError("金额修改须填写备注（补发/扣减原因）")
        entry.amount = new_amount
        entry.note = note
        return entry

    async def confirm_run(self, session: AsyncSession, run_id: str) -> PayrollRun:
        """确认批次：明细锁定 + 批次总额/人数回写。"""
        run = await self.get_run(session, run_id)
        if run.status != "draft":
            raise ConflictError(f"批次状态为 {run.status}，不可确认")
        totals = (
            await session.execute(
                select(
                    func.coalesce(func.sum(PayrollEntry.amount), 0),
                    func.count(func.distinct(PayrollEntry.employee_id)),
                ).where(PayrollEntry.run_id == run_id)
            )
        ).one()
        run.total_amount = totals[0]
        run.employee_count = int(totals[1])
        run.status = "confirmed"
        return run

    async def pay_run(self, session: AsyncSession, run_id: str) -> PayrollRun:
        """标记发放：confirmed → paid（员工自助可见当期薪酬单）。"""
        run = await self.get_run(session, run_id)
        if run.status != "confirmed":
            raise ConflictError(f"批次状态为 {run.status}，不可发放")
        run.status = "paid"
        run.pay_date = date.today()
        return run

    async def cancel_run(self, session: AsyncSession, run_id: str) -> PayrollRun:
        """取消批次（已发放不可取消；明细行保留供追溯）。"""
        run = await self.get_run(session, run_id)
        if run.status == "paid":
            raise ConflictError("已发放批次不可取消")
        if run.status == "cancelled":
            raise ConflictError("批次已取消")
        run.status = "cancelled"
        return run

    # ── 试算 ──

    async def calculate_run(self, session: AsyncSession, run_id: str) -> PayrollRun:
        """试算生成明细：逐在职员工 × 月度固定项，调薪跨区间按天分段折算。

        draft 态可重复执行（重算先清旧明细）；performance 类按最近 closed
        周期评估系数放大（无评估兜底 1.0）；非月度固定项（年终奖等）由
        HR 批次内手工补录。
        """
        run = await self.get_run(session, run_id)
        if run.status != "draft":
            raise ConflictError(f"批次状态为 {run.status}，仅草稿可试算")
        year, month = int(run.period[:4]), int(run.period[5:7])
        period_start = date(year, month, 1)
        period_end = date(year, month, calendar.monthrange(year, month)[1])
        days_in_month = Decimal(period_end.day)

        existing = (
            await session.execute(
                select(PayrollEntry.id).where(PayrollEntry.run_id == run_id)
            )
        ).scalars().all()
        if existing:
            for entry_id in existing:
                entry = await session.get(PayrollEntry, entry_id)
                if entry:
                    await session.delete(entry)

        item_rows = (
            await session.execute(
                select(SalaryItem).where(
                    SalaryItem.can_edit.is_(True),
                )
            )
        ).scalars().all()
        fixed_items = [
            item
            for item in item_rows
            if (item.ext_data or {}).get("monthly_fixed")
        ]

        employees = (
            await session.execute(
                select(Employee).where(
                    Employee.status.in_(_PAYROLL_EMPLOYEE_STATUSES)
                )
            )
        ).scalars().all()

        coeff_map = await self._perf_coefficient_map(
            session, [str(employee.id) for employee in employees]
        )

        entry_count = 0
        for employee in employees:
            for item in fixed_items:
                segments = await self._effective_segments(
                    session, str(employee.id), str(item.id), period_start, period_end
                )
                if not segments:
                    continue
                amount = sum(
                    (seg_amount for _, _, seg_amount in segments), Decimal("0")
                ).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
                if item.category == "performance":
                    amount = (
                        amount
                        * coeff_map.get(str(employee.id), _PERF_COEFFICIENT)
                    ).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
                note = None
                if len(segments) > 1:
                    note = "；".join(
                        f"{start}~{end} 分段折算" for start, end, _ in segments
                    )
                session.add(
                    PayrollEntry(
                        tenant_id=get_tenant_id(),
                        run_id=run_id,
                        employee_id=str(employee.id),
                        item_id=str(item.id),
                        item_code=item.code,
                        amount=amount,
                        note=note,
                    )
                )
                entry_count += 1

        _logger.info(
            f"发薪试算完成 run={run_id} period={run.period} "
            f"entries={entry_count} employees={len(employees)}"
        )
        return run

    async def _perf_coefficient_map(
        self,
        session: AsyncSession,
        employee_ids: list[str],
    ) -> dict[str, Decimal]:
        """员工 → 最近 closed 周期评估系数（收口时写入 perf_reviews.coefficient）。

        按 cycle end_date 倒序取每员工最新一条；无 closed 周期评估的员工不在
        映射中，消费侧回退 _PERF_COEFFICIENT（1.0）。
        """
        if not employee_ids:
            return {}
        rows = (
            await session.execute(
                select(PerfReview.employee_id, PerfReview.coefficient)
                .join(PerfCycle, PerfReview.cycle_id == PerfCycle.id)
                .where(
                    PerfCycle.status == "closed",
                    PerfReview.employee_id.in_(employee_ids),
                    PerfReview.coefficient.is_not(None),
                )
                .order_by(
                    PerfCycle.end_date.desc(), PerfReview.created_at.desc()
                )
            )
        ).all()
        coefficients: dict[str, Decimal] = {}
        for employee_id, coefficient in rows:
            if employee_id not in coefficients:
                coefficients[employee_id] = Decimal(str(coefficient))
        return coefficients

    async def _effective_segments(
        self,
        session: AsyncSession,
        employee_id: str,
        item_id: str,
        period_start: date,
        period_end: date,
    ) -> list[tuple[date, date, Decimal]]:
        """当期生效定薪区间与发薪期窗的交集分段（起止日 + 天数加权金额）。

        日金额 = 月金额 / 当月天数；金额 = 月金额 × 交集天数 / 当月天数。
        """
        packages = (
            await session.execute(
                select(EmployeeSalaryPackage).where(
                    EmployeeSalaryPackage.employee_id == employee_id,
                    EmployeeSalaryPackage.item_id == item_id,
                    EmployeeSalaryPackage.effective_from <= period_end,
                    EmployeeSalaryPackage.effective_to.is_(None)
                    | (EmployeeSalaryPackage.effective_to >= period_start),
                )
            )
        ).scalars().all()

        segments: list[tuple[date, date, Decimal]] = []
        for package in packages:
            start = max(package.effective_from, period_start)
            end = min(package.effective_to or period_end, period_end)
            if start > end:
                continue
            days = Decimal((end - start).days + 1)
            amount = (
                Decimal(str(package.amount)) * days / Decimal(period_end.day)
            ).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
            segments.append((start, end, amount))
        segments.sort(key=lambda seg: seg[0])
        return segments

    # ── 标准代发导出 ──

    async def export_run(self, session: AsyncSession, run_id: str) -> tuple[str, bytes]:
        """标准代发文件（xlsx 单 sheet）：工号/姓名/证件号/开户行/银行卡号/应发/实发/期间。

        仅 confirmed/paid 态可导；证件号/银行卡为列级密文解密明文，
        调用方须校验 hr:payroll:export 并写审计。实发 = 应发 - 扣减类合计。
        """
        run = await self.get_run(session, run_id)
        if run.status not in ("confirmed", "paid"):
            raise ConflictError(f"批次状态为 {run.status}，仅确认/已发放批次可导出代发文件")

        rows = (
            await session.execute(
                select(
                    PayrollEntry.employee_id,
                    Employee.employee_no,
                    Employee.name,
                    Employee.id_card_enc,
                    Employee.bank_card_enc,
                    Employee.bank_name,
                    SalaryItem.category,
                    PayrollEntry.amount,
                )
                .join(Employee, PayrollEntry.employee_id == Employee.id)
                .join(SalaryItem, PayrollEntry.item_id == SalaryItem.id)
                .where(PayrollEntry.run_id == run_id)
                .order_by(Employee.employee_no)
            )
        ).all()

        from hr.services.employee_service import EmployeeService

        per_employee: dict[str, dict] = {}
        for row in rows:
            employee_id, employee_no, name, id_enc, bank_enc, bank_name, category, amount = row
            item = per_employee.setdefault(
                employee_id,
                {
                    "employee_no": employee_no,
                    "name": name,
                    "id_card_enc": id_enc,
                    "bank_card_enc": bank_enc,
                    "bank_name": bank_name,
                    "gross": Decimal("0"),
                    "deduction": Decimal("0"),
                },
            )
            if category == "deduction":
                item["deduction"] += amount
            else:
                item["gross"] += amount

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "标准代发"
        sheet.append(["工号", "姓名", "证件号", "开户行", "银行卡号", "应发", "实发", "期间"])
        ordered = sorted(per_employee.items(), key=lambda pair: pair[1]["employee_no"])
        for _, info in ordered:
            gross = info["gross"].quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
            net = (gross - info["deduction"]).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
            sheet.append(
                [
                    info["employee_no"],
                    info["name"],
                    EmployeeService._decrypt_sensitive(info["id_card_enc"], "证件号"),
                    info["bank_name"],
                    EmployeeService._decrypt_sensitive(info["bank_card_enc"], "银行卡号"),
                    float(gross),
                    float(net),
                    run.period,
                ]
            )

        buffer = BytesIO()
        workbook.save(buffer)
        return f"标准代发-{run.period}.xlsx", buffer.getvalue()

    # ── 响应构造 ──

    def to_run_response(self, run: PayrollRun) -> PayrollRunResponse:
        return PayrollRunResponse(
            id=str(run.id),
            period=run.period,
            status=run.status,
            total_amount=float(run.total_amount) if run.total_amount is not None else None,
            employee_count=run.employee_count,
            pay_date=run.pay_date,
        )

    def to_entry_response(
        self, entry: PayrollEntry, employee: Employee | None = None
    ) -> PayrollEntryResponse:
        return PayrollEntryResponse(
            id=str(entry.id),
            run_id=str(entry.run_id),
            employee_id=str(entry.employee_id),
            employee_no=employee.employee_no if employee else None,
            employee_name=employee.name if employee else None,
            item_id=str(entry.item_id),
            item_code=entry.item_code,
            amount=float(entry.amount),
            note=entry.note,
        )


payroll_service = PayrollService()
