"""报表 Excel 导出服务：六域取数 + openpyxl 工作簿组装（单 sheet 分段布局）"""

from io import BytesIO
from datetime import date

from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

from hr.services.attrition_risk_service import attrition_risk_service
from hr.services.report_service import report_service

EXPORT_DOMAINS = (
    "overview",
    "turnover",
    "recruiting",
    "comp-dist",
    "performance",
    "attrition-risk",
)

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _append_section(rows: list[list[object]], headers: list[str], data: list[list[object]]) -> None:
    rows.append(headers)
    rows.extend(data)
    rows.append([])


class ReportExportService:
    """报表导出（复用各域 get_* 同口径取数，仅做行集组装与 xlsx 生成）"""

    async def build_export(
        self,
        session: AsyncSession,
        *,
        domain: str,
        date_from: date | None = None,
        date_to: date | None = None,
        org_id: str | None = None,
        months: int = 6,
        include_comp: bool = True,
    ) -> tuple[str, bytes]:
        """返回 (文件名, xlsx 字节)；include_comp 供 attrition-risk 透传薪酬权限口径。"""
        builder = {
            "overview": self._overview_rows,
            "turnover": self._turnover_rows,
            "recruiting": self._recruiting_rows,
            "comp-dist": self._comp_dist_rows,
            "performance": self._performance_rows,
            "attrition-risk": self._attrition_risk_rows,
        }.get(domain)
        if builder is None:
            raise ValueError(f"未知导出域: {domain}")
        rows = await builder(
            session,
            date_from=date_from,
            date_to=date_to,
            org_id=org_id,
            months=months,
            include_comp=include_comp,
        )

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = domain
        for row in rows:
            sheet.append(row)
        buffer = BytesIO()
        workbook.save(buffer)
        content = buffer.getvalue()

        span = (
            f"{date_from}~{date_to}"
            if date_from and date_to
            else date.today().isoformat()
        )
        return f"报表导出-{domain}-{span}.xlsx", content

    async def _overview_rows(
        self,
        session: AsyncSession,
        *,
        date_from: date | None,
        date_to: date | None,
        org_id: str | None,
        months: int,
        include_comp: bool,
    ) -> list[list[object]]:
        data = await report_service.get_overview(
            session, date_from=date_from, date_to=date_to, org_id=org_id, months=months
        )
        rows: list[list[object]] = []
        _append_section(
            rows,
            ["指标", "数值"],
            [
                ["在编人数", data.cards.active_count],
                ["试用期人数", data.cards.probation_count],
                ["本月新入职", data.cards.month_hired_count],
                ["离职率", data.cards.turnover_rate],
            ],
        )
        _append_section(
            rows,
            ["月份", "在编人数"],
            [[point.month, point.count] for point in data.headcount_trend],
        )
        _append_section(
            rows,
            ["组织ID", "人数"],
            [
                [item.org_id or "未分配组织", item.count]
                for item in data.org_distribution
            ],
        )
        return rows

    async def _turnover_rows(
        self,
        session: AsyncSession,
        *,
        date_from: date | None,
        date_to: date | None,
        org_id: str | None,
        months: int,
        include_comp: bool,
    ) -> list[list[object]]:
        data = await report_service.get_turnover(
            session, date_from=date_from, date_to=date_to, org_id=org_id, months=months
        )
        rows: list[list[object]] = [
            ["月份", "离职人数", "月均在编", "离职率"],
            *[[p.month, p.offboarded, p.avg_headcount, p.rate] for p in data.points],
        ]
        return rows

    async def _recruiting_rows(
        self,
        session: AsyncSession,
        *,
        date_from: date | None,
        date_to: date | None,
        org_id: str | None,
        months: int,
        include_comp: bool,
    ) -> list[list[object]]:
        data = await report_service.get_recruiting(
            session, date_from=date_from, date_to=date_to, org_id=org_id
        )
        rows: list[list[object]] = []
        _append_section(
            rows,
            ["阶段", "人数"],
            [[item.stage, item.count] for item in data.funnel],
        )
        _append_section(
            rows,
            ["渠道", "阶段", "人数"],
            [
                [item.channel or "未归集渠道", stage, count]
                for item in data.channels
                for stage, count in item.stages.items()
            ],
        )
        return rows

    async def _comp_dist_rows(
        self,
        session: AsyncSession,
        *,
        date_from: date | None,
        date_to: date | None,
        org_id: str | None,
        months: int,
        include_comp: bool,
    ) -> list[list[object]]:
        data = await report_service.get_comp_distribution(session)
        rows: list[list[object]] = [["维度", "键", "人数", "下限", "中位", "上限"]]
        rows.extend(
            ["职级", item.key or "未定级", item.count, item.min_amount, item.mid_amount, item.max_amount]
            for item in data.by_level
        )
        rows.extend(
            ["组织", item.key or "未分配组织", item.count, item.min_amount, item.mid_amount, item.max_amount]
            for item in data.by_org
        )
        return rows

    async def _performance_rows(
        self,
        session: AsyncSession,
        *,
        date_from: date | None,
        date_to: date | None,
        org_id: str | None,
        months: int,
        include_comp: bool,
    ) -> list[list[object]]:
        data = await report_service.get_performance(session)
        rows: list[list[object]] = [["周期", "截止日", "参评人数", "平均分"]]
        rows.extend(
            [cycle.cycle_name, cycle.end_date, cycle.total, cycle.avg_score]
            for cycle in data.cycles
        )
        rows.append([])
        rows.append(["周期", "评级", "人数"])
        rows.extend(
            [cycle.cycle_name, rating, count]
            for cycle in data.cycles
            for rating, count in cycle.ratings.items()
        )
        return rows

    async def _attrition_risk_rows(
        self,
        session: AsyncSession,
        *,
        date_from: date | None,
        date_to: date | None,
        org_id: str | None,
        months: int,
        include_comp: bool,
    ) -> list[list[object]]:
        data = await attrition_risk_service.get_risk_list(
            session, org_id=org_id, include_comp=include_comp
        )
        rows: list[list[object]] = [
            ["姓名", "工号", "组织ID", "风险分", "风险等级", "风险因子"],
            *[
                [item.name, item.employee_no, item.org_id, item.score, item.level, "；".join(item.factors)]
                for item in data.items
            ],
        ]
        return rows


report_export_service = ReportExportService()
