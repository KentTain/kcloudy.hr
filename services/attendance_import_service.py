"""考勤导入服务：Excel 通道（模板/预检/导入）+ AI 通道（临时区/解析/确认）

双通道同键覆盖语义统一走 attendance_service.upsert_record；
行级校验：员工匹配（工号+姓名）、日期与时间格式、关键字段缺失。
"""

import base64
import json
from datetime import date, datetime, time
from io import BytesIO

from loguru import logger
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.clients.document_client import get_document_client
from framework.common.ctx import get_tenant_id
from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError
from framework.tasks.service import task_service

from hr.models import AttendanceImportBatch, Employee
from hr.schemas.attendance import AttendanceRowResult
from hr.services.attendance_service import attendance_service, judge_status

_logger = logger.bind(name=__name__)

_TEMPLATE_HEADERS = [
    "工号",
    "姓名",
    "部门",
    "日期",
    "上班打卡时间",
    "下班打卡时间",
    "加班时长（小时）",
    "备注",
]

_AI_PARSE_TASK_TYPE = "hr_attendance_parse"
_AI_PARSE_QUEUE = "hr-attendance"

_FIELD_LABELS = {
    "employee_no": "工号",
    "employee_name": "姓名",
    "work_date": "日期",
    "check_in": "上班打卡时间",
    "check_out": "下班打卡时间",
}

_LLM_PARSE_PROMPT = """你是考勤数据解析助手。从下面的表格内容中识别表头与数据行，输出严格 JSON（不含任何多余文本），结构：
{"field_mapping": {"employee_no": "识别出的工号列名", "employee_name": "...", "work_date": "...", "check_in": "...", "check_out": "...", "overtime_hours": "...", "remark": "..."}, "rows": [{"employee_no": "工号", "employee_name": "姓名", "work_date": "yyyy-MM-dd", "check_in": "HH:mm", "check_out": "HH:mm", "overtime_hours": 数值或null, "remark": "备注或null"}]}
要求：识别不出映射的键置 null；日期规范化为 yyyy-MM-dd；时间规范化为 HH:mm；加班时长为数值；不臆造数据。表格内容：


"""


def _parse_date_value(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def _parse_time_value(value) -> time | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, time):
        return value
    text = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _parse_float_value(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


class AttendanceImportService:
    """考勤导入业务（Excel dryRun 预检不落库；AI 批次异步解析）"""

    # ── Excel 通道 ──

    def build_template(self) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(_TEMPLATE_HEADERS)
        buffer = BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    def encode_content(self, content: bytes) -> str:
        return base64.b64encode(content).decode()

    async def import_excel(
        self,
        session: AsyncSession,
        content: bytes,
        filename: str,
        *,
        dry_run: bool,
        operator_id: str,
    ) -> dict:
        rows = self._read_workbook_rows(content)
        employee_map = await self._load_employee_map(
            session, [row.get("employee_no") for row in rows]
        )

        results: list[AttendanceRowResult] = []
        new_count = overwrite_count = fail_count = 0
        for row in rows:
            result, parsed = self._validate_row(row, employee_map)
            results.append(result)
            if not result.parseable:
                fail_count += 1
                continue
            if dry_run:
                continue
            record, created = await attendance_service.upsert_record(
                session,
                employee_id=parsed["employee_id"],
                work_date=parsed["work_date"],
                status=parsed["status"],
                source="excel",
                check_in_time=parsed["check_in_time"],
                check_out_time=parsed["check_out_time"],
                overtime_hours=parsed["overtime_hours"],
                remark=parsed["remark"],
            )
            if created:
                new_count += 1
            else:
                overwrite_count += 1

        if dry_run:
            return self._import_result("", True, results, 0, 0, fail_count)

        batch = AttendanceImportBatch(
            tenant_id=get_tenant_id(),
            channel="excel",
            file_key=filename,
            status="completed",
            row_results=[item.model_dump() for item in results],
            new_count=new_count,
            overwrite_count=overwrite_count,
            fail_count=fail_count,
            operator_id=operator_id,
        )
        session.add(batch)
        await session.flush()
        return self._import_result(
            str(batch.id), False, results, new_count, overwrite_count, fail_count
        )

    def _read_workbook_rows(self, content: bytes) -> list[dict]:
        try:
            workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
        except Exception as exc:  # noqa: BLE001 - 上传文件内容不可控
            raise BadRequestError(f"无法解析 Excel 文件: {exc}") from exc
        sheet = workbook.active
        rows_iter = sheet.iter_rows(values_only=True)
        header = next(rows_iter, None)
        if not header or str(header[0] or "").strip() != "工号":
            raise BadRequestError("表头不符合导入模板，请下载模板后按格式填写")
        rows: list[dict] = []
        for index, cells in enumerate(rows_iter, start=2):
            if not any(cells):
                continue
            rows.append(
                {
                    "row_index": index,
                    "employee_no": cells[0],
                    "employee_name": cells[1],
                    "work_date": cells[3],
                    "check_in": cells[4],
                    "check_out": cells[5],
                    "overtime_hours": cells[6],
                    "remark": cells[7],
                }
            )
        workbook.close()
        return rows

    # ── 行级校验（Excel / AI 共用）──

    async def _load_employee_map(
        self, session: AsyncSession, employee_nos: list
    ) -> dict[str, Employee]:
        nos = sorted({str(no).strip() for no in employee_nos if no})
        if not nos:
            return {}
        rows = (
            await session.execute(
                select(Employee).where(Employee.employee_no.in_(nos))
            )
        ).scalars().all()
        return {employee.employee_no: employee for employee in rows}

    def _validate_row(
        self, row: dict, employee_map: dict[str, Employee]
    ) -> tuple[AttendanceRowResult, dict | None]:
        row_index = row.get("row_index", 0)
        employee_no = str(row.get("employee_no") or "").strip() or None
        employee_name = str(row.get("employee_name") or "").strip() or None
        work_date = _parse_date_value(row.get("work_date"))
        check_in = _parse_time_value(row.get("check_in"))
        check_out = _parse_time_value(row.get("check_out"))
        overtime = _parse_float_value(row.get("overtime_hours"))
        remark = row.get("remark")

        base = {
            "row_index": row_index,
            "employee_no": employee_no,
            "employee_name": employee_name,
            "work_date": work_date.isoformat() if work_date else None,
        }

        missing = [
            label
            for field, label in _FIELD_LABELS.items()
            if (field != "employee_name" and not row.get(field))
        ]
        if missing:
            result = AttendanceRowResult(
                **base, parseable=False, error=f"字段缺失: {'、'.join(missing)}"
            )
            return result, None

        employee = employee_map.get(employee_no)
        if employee is None or str(employee.name) != employee_name:
            result = AttendanceRowResult(
                **base,
                parseable=False,
                error=f"未匹配员工: {employee_no} {employee_name}",
            )
            return result, None

        if work_date is None or (check_in is None and check_out is None):
            result = AttendanceRowResult(
                **base, parseable=False, error="日期或打卡时间格式错误"
            )
            return result, None

        data = {
            "employee_id": str(employee.id),
            "work_date": work_date.isoformat(),
            "check_in": check_in.strftime("%H:%M") if check_in else None,
            "check_out": check_out.strftime("%H:%M") if check_out else None,
            "overtime_hours": overtime,
            "remark": str(remark).strip() if remark else None,
        }
        result = AttendanceRowResult(
            **base,
            parseable=True,
            data={
                **data,
                "work_date": work_date.isoformat(),
            },
        )
        return result, {
            **data,
            "work_date": work_date,
            "check_in_time": datetime.combine(work_date, check_in)
            if check_in
            else None,
            "check_out_time": datetime.combine(work_date, check_out)
            if check_out
            else None,
            "status": judge_status(
                datetime.combine(work_date, check_in) if check_in else None,
                datetime.combine(work_date, check_out) if check_out else None,
            ),
        }

    @staticmethod
    def _import_result(
        batch_id: str,
        dry_run: bool,
        results: list[AttendanceRowResult],
        new_count: int,
        overwrite_count: int,
        fail_count: int,
    ) -> dict:
        return {
            "batch_id": batch_id,
            "dry_run": dry_run,
            "row_results": [item.model_dump() for item in results],
            "new_count": new_count,
            "overwrite_count": overwrite_count,
            "fail_count": fail_count,
        }

    # ── AI 通道 ──

    async def create_ai_batch(
        self,
        session: AsyncSession,
        content: bytes,
        filename: str,
        *,
        operator_id: str,
    ) -> dict:
        tenant_id = get_tenant_id()
        file_vo = await get_document_client().store_temp_file(
            session,
            tenant_id=tenant_id,
            user_id=operator_id,
            filename=filename,
            content=content,
            purpose="hr_attendance",
        )
        batch = AttendanceImportBatch(
            tenant_id=tenant_id,
            channel="ai",
            file_key=str(file_vo["id"]),
            status="pending",
            operator_id=operator_id,
        )
        session.add(batch)
        await session.flush()

        task = await task_service.submit(
            session,
            task_type=_AI_PARSE_TASK_TYPE,
            queue=_AI_PARSE_QUEUE,
            config_snapshot={
                "batch_id": str(batch.id),
                "tenant_id": get_tenant_id(),
            },
            resource_type="hr_attendance_import_batch",
            resource_id=str(batch.id),
        )
        return {"batch_id": str(batch.id), "task_id": str(task.id)}

    async def get_batch(self, session: AsyncSession, batch_id: str) -> dict:
        batch = await session.get(AttendanceImportBatch, batch_id)
        if not batch:
            raise NotFoundError(f"导入批次 {batch_id} 不存在")
        return self.to_batch_response(batch)

    async def list_ai_batches(
        self, session: AsyncSession, *, page: int = 1, page_size: int = 20
    ) -> dict:
        """AI 导入批次列表（时间倒序），供导入弹窗回看历史批次。"""
        conditions = [AttendanceImportBatch.channel == "ai"]
        total_stmt = select(func.count()).select_from(AttendanceImportBatch).where(*conditions)
        total = (await session.execute(total_stmt)).scalar_one()
        rows = (
            await session.execute(
                select(AttendanceImportBatch)
                .where(*conditions)
                .order_by(AttendanceImportBatch.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return {
            "total": total,
            "items": [self.to_batch_response(batch) for batch in rows],
        }

    async def export_failure_rows(
        self, session: AsyncSession, batch_id: str
    ) -> tuple[str, bytes]:
        """失败行明细导出 xlsx（行号/工号/姓名/考勤日期/失败原因），base64 前置。"""
        batch = await session.get(AttendanceImportBatch, batch_id)
        if not batch:
            raise NotFoundError(f"导入批次 {batch_id} 不存在")
        failed = [
            item
            for item in (batch.row_results or [])
            if not item.get("parseable") or item.get("error")
        ]
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "失败明细"
        sheet.append(["行号", "工号", "姓名", "考勤日期", "失败原因"])
        for item in failed:
            sheet.append(
                [
                    item.get("row_index"),
                    item.get("employee_no") or "",
                    item.get("employee_name") or "",
                    item.get("work_date") or "",
                    item.get("error") or "",
                ]
            )
        buffer = BytesIO()
        workbook.save(buffer)
        return f"考勤导入失败明细-{batch_id[:8]}.xlsx", buffer.getvalue()

    async def confirm_batch(
        self, session: AsyncSession, batch_id: str, row_indexes: list[int]
    ) -> dict:
        batch = await session.get(AttendanceImportBatch, batch_id)
        if not batch:
            raise NotFoundError(f"导入批次 {batch_id} 不存在")
        if batch.status != "parsed":
            raise ConflictError(f"批次状态为 {batch.status}，仅解析完成可确认导入")

        selected = set(row_indexes)
        row_results = batch.row_results or []
        new_count = overwrite_count = discard_count = 0
        for item in row_results:
            if item.get("row_index") not in selected or not item.get("parseable"):
                discard_count += 1
                continue
            data = item.get("data") or {}
            record, created = await attendance_service.upsert_record(
                session,
                employee_id=data["employee_id"],
                work_date=date.fromisoformat(data["work_date"]),
                status=judge_status(
                    self._combine(data["work_date"], data.get("check_in")),
                    self._combine(data["work_date"], data.get("check_out")),
                ),
                source="ai",
                check_in_time=self._combine(data["work_date"], data.get("check_in")),
                check_out_time=self._combine(data["work_date"], data.get("check_out")),
                overtime_hours=data.get("overtime_hours"),
                remark=data.get("remark"),
            )
            if created:
                new_count += 1
            else:
                overwrite_count += 1

        batch.new_count = new_count
        batch.overwrite_count = overwrite_count
        batch.discard_count = discard_count
        batch.status = "completed"
        await get_document_client().discard_file(session, str(batch.file_key))
        await session.flush()
        return {
            "batch_id": str(batch.id),
            "new_count": new_count,
            "overwrite_count": overwrite_count,
            "discard_count": discard_count,
        }

    async def retry_batch(self, session: AsyncSession, batch_id: str) -> dict:
        batch = await session.get(AttendanceImportBatch, batch_id)
        if not batch:
            raise NotFoundError(f"导入批次 {batch_id} 不存在")
        if batch.status != "failed":
            raise ConflictError(f"批次状态为 {batch.status}，仅解析失败可重试")
        batch.status = "pending"
        task = await task_service.submit(
            session,
            task_type=_AI_PARSE_TASK_TYPE,
            queue=_AI_PARSE_QUEUE,
            config_snapshot={
                "batch_id": str(batch.id),
                "tenant_id": get_tenant_id(),
            },
            resource_type="hr_attendance_import_batch",
            resource_id=str(batch.id),
        )
        return {"batch_id": str(batch.id), "task_id": str(task.id)}

    # ── AI 解析执行（消费者调用）──

    async def parse_batch(self, session: AsyncSession, batch_id: str) -> None:
        """解析批次原文档 → LLM 结构化抽取 → 行级校验回写（status=parsed/failed）。"""
        batch = await session.get(AttendanceImportBatch, batch_id)
        if not batch or batch.status not in ("pending", "failed"):
            return
        batch.status = "parsing"
        await session.flush()

        content = await get_document_client().download_file_content(
            session, str(batch.file_key)
        )
        if content is None:
            batch.status = "failed"
            await session.flush()
            return
        try:
            raw_rows = self._read_workbook_rows(content)
        except BadRequestError as exc:
            # 非表格文档（截图/PDF）一期不支持结构化解析，可转存表格后重试
            _logger.warning(f"考勤 AI 解析不支持文档格式 batch={batch_id}: {exc}")
            batch.status = "failed"
            await session.flush()
            return

        field_mapping, llm_rows = await self._llm_extract(raw_rows)
        employee_map = await self._load_employee_map(
            session, [row.get("employee_no") for row in llm_rows]
        )
        results: list[AttendanceRowResult] = []
        for index, row in enumerate(llm_rows, start=2):
            row = {**row, "row_index": index}
            result, _ = self._validate_row(row, employee_map)
            results.append(result)

        batch.field_mapping = field_mapping
        batch.row_results = [item.model_dump() for item in results]
        batch.status = "parsed"
        await session.flush()
        _logger.info(f"考勤 AI 解析完成 batch={batch_id} rows={len(results)}")

    async def _llm_extract(self, raw_rows: list[dict]) -> tuple[dict, list[dict]]:
        from hr.integration.llm_client import llm_chat

        table_text = "\n".join(
            " | ".join(
                f"{key}={'' if value is None else value}"
                for key, value in row.items()
            )
            for row in raw_rows
        )
        content = await llm_chat(
            get_tenant_id(),
            [
                {"role": "system", "content": "你输出严格的 JSON，不含任何多余文本。"},
                {"role": "user", "content": _LLM_PARSE_PROMPT + table_text},
            ],
        )
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise BadRequestError(f"AI 解析结果非 JSON: {exc}") from exc
        field_mapping = payload.get("field_mapping") or {}
        rows = payload.get("rows") or []
        return dict(field_mapping), [dict(row) for row in rows if isinstance(row, dict)]

    @staticmethod
    def _combine(work_date_iso: str, clock: str | None) -> datetime | None:
        if not clock:
            return None
        return datetime.combine(
            date.fromisoformat(work_date_iso), time.fromisoformat(clock)
        )

    def to_batch_response(self, batch: AttendanceImportBatch) -> dict:
        file_name = None
        if batch.channel == "excel":
            file_name = batch.file_key
        return {
            "id": str(batch.id),
            "channel": batch.channel,
            "status": batch.status,
            "file_id": None if batch.channel == "excel" else str(batch.file_key),
            "filename": file_name,
            "field_mapping": batch.field_mapping,
            "row_results": batch.row_results,
            "new_count": batch.new_count,
            "overwrite_count": batch.overwrite_count,
            "discard_count": batch.discard_count,
            "fail_count": batch.fail_count,
            "created_at": batch.created_at.isoformat() if batch.created_at else None,
        }


attendance_import_service = AttendanceImportService()
