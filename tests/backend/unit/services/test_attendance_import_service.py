"""考勤导入服务单元测试

覆盖：Excel 模板与 dryRun 预检不落库、行级校验三类（字段缺失/未匹配员工/
格式错误）、正式导入新增/覆盖计数与批次落库、AI 批次状态机（pending→parsing→
parsed→completed；failed 可重试）。
"""

import json
from datetime import date, datetime
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import (
    BadRequestError,
    ConflictError,
    NotFoundError,
)
from framework.tenant.context import TenantContext

from hr.models import AttendanceImportBatch, AttendanceRecord, Employee
from hr.services.attendance_import_service import attendance_import_service


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

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


def _mock_session(get_map=None, execute_results=None) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.flush = AsyncMock()
    added: list = []
    session.add = MagicMock(side_effect=added.append)
    session._added = added
    session.get = AsyncMock(
        side_effect=lambda model, pk: (get_map or {}).get((model.__name__, str(pk)))
    )
    session.execute = AsyncMock(
        side_effect=list(execute_results) if execute_results else []
    )
    return session


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


def _workbook_bytes(rows: list[list]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["工号", "姓名", "部门", "日期", "上班打卡时间", "下班打卡时间", "加班时长（小时）", "备注"])
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _tenant_context():
    TenantContext.set_tenant_id("t-1")
    yield
    TenantContext.clear()


class TestRowValidation:
    """行级校验三类"""

    def test_missing_required_field(self):
        result, parsed = attendance_import_service._validate_row(
            {"row_index": 2, "employee_no": None, "employee_name": "张三", "work_date": "2026-10-16"},
            {},
        )
        assert result.parseable is False
        assert "字段缺失" in result.error
        assert parsed is None

    def test_employee_not_matched(self):
        result, parsed = attendance_import_service._validate_row(
            {
                "row_index": 2,
                "employee_no": "EMP0001",
                "employee_name": "张三",
                "work_date": "2026-10-16",
                "check_in": "09:00",
                "check_out": "18:00",
            },
            {"EMP0001": _employee(name="李四")},
        )
        assert result.parseable is False
        assert "未匹配员工" in result.error

    def test_bad_date_format(self):
        result, parsed = attendance_import_service._validate_row(
            {
                "row_index": 2,
                "employee_no": "EMP0001",
                "employee_name": "张三",
                "work_date": "not-a-date",
                "check_in": "09:00",
                "check_out": "18:00",
            },
            {"EMP0001": _employee()},
        )
        assert result.parseable is False
        assert "格式错误" in result.error

    def test_parseable_row_judges_status(self):
        result, parsed = attendance_import_service._validate_row(
            {
                "row_index": 2,
                "employee_no": "EMP0001",
                "employee_name": "张三",
                "work_date": "2026-10-16",
                "check_in": "09:30",
                "check_out": "18:00",
            },
            {"EMP0001": _employee()},
        )
        assert result.parseable is True
        assert parsed["status"] == "late"
        assert parsed["employee_id"] == "emp-1"
        assert parsed["check_in_time"] == datetime(2026, 10, 16, 9, 30)


class TestExcelImport:
    """Excel 通道"""

    @pytest.mark.asyncio
    async def test_dry_run_writes_nothing(self):
        content = _workbook_bytes([["EMP0001", "张三", "研发部", "2026-10-16", "09:00", "18:00", None, None]])
        session = _mock_session(
            execute_results=[
                _FakeResult(rows=[_employee()]),  # 员工映射
                _FakeResult(rows=[]),             # upsert 查 existing
            ]
        )
        result = await attendance_import_service.import_excel(
            session, content, "考勤.xlsx", dry_run=True, operator_id="u-1"
        )
        assert result["dry_run"] is True
        assert result["new_count"] == 0
        assert result["fail_count"] == 0
        assert not [o for o in session._added if isinstance(o, AttendanceImportBatch)]

    @pytest.mark.asyncio
    async def test_formal_import_counts_new_and_overwrite(self):
        content = _workbook_bytes(
            [
                ["EMP0001", "张三", "研发部", "2026-10-16", "09:00", "18:00", None, None],
                ["EMP0001", "张三", "研发部", "2026-10-17", "09:00", "18:00", None, None],
            ]
        )
        existing = AttendanceRecord(
            id="rec-1", tenant_id="t-1", employee_id="emp-1",
            work_date=date(2026, 10, 17), status="absent", source="excel",
        )
        session = _mock_session(
            execute_results=[
                _FakeResult(rows=[_employee()]),  # 员工映射
                _FakeResult(rows=[]),             # 16 日无既有记录 → 新增
                _FakeResult(rows=[existing]),     # 17 日有既有记录 → 覆盖
            ]
        )
        result = await attendance_import_service.import_excel(
            session, content, "考勤.xlsx", dry_run=False, operator_id="u-1"
        )
        assert result["new_count"] == 1
        assert result["overwrite_count"] == 1
        batches = [o for o in session._added if isinstance(o, AttendanceImportBatch)]
        assert len(batches) == 1
        assert batches[0].tenant_id == "t-1"
        assert batches[0].status == "completed"

    def test_bad_header_rejected(self):
        workbook = Workbook()
        workbook.active.append(["编号", "姓名"])
        buffer = BytesIO()
        workbook.save(buffer)
        with pytest.raises(BadRequestError, match="模板"):
            attendance_import_service._read_workbook_rows(buffer.getvalue())

    @pytest.mark.asyncio
    async def test_template_downloadable(self):
        content = attendance_import_service.build_template()
        rows = attendance_import_service._read_workbook_rows(content)
        assert rows == []


class TestAIBatchLifecycle:
    """AI 批次状态机"""

    @pytest.mark.asyncio
    async def test_create_batch_uploads_temp_and_submits_task(self):
        session = _mock_session()
        file_vo = {"id": "file-1"}
        task = MagicMock()
        task.id = "task-1"
        with (
            patch(
                "hr.services.attendance_import_service.get_document_client"
            ) as client_factory,
            patch(
                "framework.tasks.service.task_service.submit",
                new=AsyncMock(return_value=task),
            ) as submit,
        ):
            client_factory.return_value.store_temp_file = AsyncMock(return_value=file_vo)
            result = await attendance_import_service.create_ai_batch(
                session, b"content", "考勤.xlsx", operator_id="u-1"
            )
        assert result == {"batch_id": result["batch_id"], "task_id": "task-1"}
        batch = session._added[0]
        assert batch.tenant_id == "t-1"
        assert batch.channel == "ai"
        assert batch.status == "pending"
        assert batch.file_key == "file-1"
        assert submit.await_args.kwargs["config_snapshot"]["tenant_id"] == "t-1"

    @pytest.mark.asyncio
    async def test_confirm_only_from_parsed(self):
        batch = AttendanceImportBatch(
            id="batch-1", tenant_id="t-1", channel="ai",
            file_key="file-1", status="pending", operator_id="u-1",
        )
        session = _mock_session(get_map={("AttendanceImportBatch", "batch-1"): batch})
        with pytest.raises(ConflictError, match="仅解析完成"):
            await attendance_import_service.confirm_batch(session, "batch-1", [2])

    @pytest.mark.asyncio
    async def test_confirm_writes_selected_rows(self):
        batch = AttendanceImportBatch(
            id="batch-1", tenant_id="t-1", channel="ai", file_key="file-1",
            status="parsed", operator_id="u-1",
            row_results=[
                {
                    "row_index": 2, "employee_no": "EMP0001", "employee_name": "张三",
                    "work_date": "2026-10-16", "parseable": True,
                    "data": {
                        "employee_id": "emp-1", "work_date": "2026-10-16",
                        "check_in": "09:00", "check_out": "18:00",
                        "overtime_hours": None, "remark": None,
                    },
                },
                {
                    "row_index": 3, "employee_no": "EMP0002", "employee_name": "李四",
                    "work_date": "2026-10-16", "parseable": False, "error": "未匹配员工",
                },
            ],
        )
        session = _mock_session(get_map={("AttendanceImportBatch", "batch-1"): batch})
        record = AttendanceRecord(
            id="rec-1", tenant_id="t-1", employee_id="emp-1",
            work_date=date(2026, 10, 16), status="normal", source="ai",
        )
        with (
            patch(
                "hr.services.attendance_import_service.attendance_service.upsert_record",
                new=AsyncMock(return_value=(record, True)),
            ) as upsert,
            patch(
                "hr.services.attendance_import_service.get_document_client"
            ) as client_factory,
        ):
            client_factory.return_value.discard_file = AsyncMock()
            result = await attendance_import_service.confirm_batch(
                session, "batch-1", [2, 3]
            )
        upsert.assert_awaited_once()
        assert result["new_count"] == 1
        assert result["discard_count"] == 1
        assert batch.status == "completed"
        client_factory.return_value.discard_file.assert_awaited_once_with(
            session, "file-1"
        )

    @pytest.mark.asyncio
    async def test_retry_only_failed(self):
        batch = AttendanceImportBatch(
            id="batch-1", tenant_id="t-1", channel="ai",
            file_key="file-1", status="parsed", operator_id="u-1",
        )
        session = _mock_session(get_map={("AttendanceImportBatch", "batch-1"): batch})
        with pytest.raises(ConflictError, match="仅解析失败"):
            await attendance_import_service.retry_batch(session, "batch-1")

    @pytest.mark.asyncio
    async def test_retry_resubmits_task(self):
        batch = AttendanceImportBatch(
            id="batch-1", tenant_id="t-1", channel="ai",
            file_key="file-1", status="failed", operator_id="u-1",
        )
        session = _mock_session(get_map={("AttendanceImportBatch", "batch-1"): batch})
        task = MagicMock()
        task.id = "task-2"
        with patch(
            "framework.tasks.service.task_service.submit",
            new=AsyncMock(return_value=task),
        ):
            result = await attendance_import_service.retry_batch(session, "batch-1")
        assert batch.status == "pending"
        assert result["task_id"] == "task-2"


class TestParseBatch:
    """AI 解析执行（消费者侧）"""

    @pytest.mark.asyncio
    async def test_missing_file_marks_failed(self):
        batch = AttendanceImportBatch(
            id="batch-1", tenant_id="t-1", channel="ai",
            file_key="file-1", status="pending", operator_id="u-1",
        )
        session = _mock_session(get_map={("AttendanceImportBatch", "batch-1"): batch})
        with patch(
            "hr.services.attendance_import_service.get_document_client"
        ) as client_factory:
            client_factory.return_value.download_file_content = AsyncMock(
                return_value=None
            )
            await attendance_import_service.parse_batch(session, "batch-1")
        assert batch.status == "failed"

    @pytest.mark.asyncio
    async def test_non_table_document_marks_failed(self):
        batch = AttendanceImportBatch(
            id="batch-1", tenant_id="t-1", channel="ai",
            file_key="file-1", status="pending", operator_id="u-1",
        )
        session = _mock_session(get_map={("AttendanceImportBatch", "batch-1"): batch})
        with (
            patch(
                "hr.services.attendance_import_service.get_document_client"
            ) as client_factory,
            patch.object(
                attendance_import_service,
                "_read_workbook_rows",
                side_effect=BadRequestError("表头不符合导入模板"),
            ),
        ):
            client_factory.return_value.download_file_content = AsyncMock(
                return_value=b"pdf-bytes"
            )
            await attendance_import_service.parse_batch(session, "batch-1")
        assert batch.status == "failed"

    @pytest.mark.asyncio
    async def test_success_writes_row_results(self):
        batch = AttendanceImportBatch(
            id="batch-1", tenant_id="t-1", channel="ai",
            file_key="file-1", status="pending", operator_id="u-1",
        )
        session = _mock_session(
            get_map={("AttendanceImportBatch", "batch-1"): batch},
            execute_results=[_FakeResult(rows=[_employee()])],
        )
        llm_payload = json.dumps(
            {
                "field_mapping": {"employee_no": "工号"},
                "rows": [
                    {
                        "employee_no": "EMP0001",
                        "employee_name": "张三",
                        "work_date": "2026-10-16",
                        "check_in": "09:00",
                        "check_out": "18:00",
                        "overtime_hours": None,
                        "remark": None,
                    }
                ],
            }
        )
        with (
            patch(
                "hr.services.attendance_import_service.get_document_client"
            ) as client_factory,
            patch.object(
                attendance_import_service,
                "_read_workbook_rows",
                return_value=[{"employee_no": "EMP0001"}],
            ),
            patch.object(
                attendance_import_service,
                "_llm_extract",
                new=AsyncMock(
                    return_value=(
                        {"employee_no": "工号"},
                        [
                            {
                                "employee_no": "EMP0001",
                                "employee_name": "张三",
                                "work_date": "2026-10-16",
                                "check_in": "09:00",
                                "check_out": "18:00",
                            }
                        ],
                    )
                ),
            ),
        ):
            client_factory.return_value.download_file_content = AsyncMock(
                return_value=b"xlsx-bytes"
            )
            await attendance_import_service.parse_batch(session, "batch-1")
        assert batch.status == "parsed"
        assert len(batch.row_results) == 1
        assert batch.row_results[0]["parseable"] is True
        assert batch.field_mapping == {"employee_no": "工号"}


class TestAIBatchListing:
    """AI 批次列表与失败明细导出（批 D 考勤 AI 批次两端点服务侧）"""

    @pytest.mark.asyncio
    async def test_list_ai_batches_returns_page(self):
        batch_a = AttendanceImportBatch(
            id="batch-aaaaaaaa-1", tenant_id="t-1", channel="ai",
            file_key="file-1", status="completed", operator_id="u-1",
            new_count=5, fail_count=1,
            created_at=datetime(2026, 10, 18, 10, 0, 0),
        )
        batch_b = AttendanceImportBatch(
            id="batch-bbbbbbbb-2", tenant_id="t-1", channel="ai",
            file_key="file-2", status="parsed", operator_id="u-1",
            created_at=datetime(2026, 10, 17, 9, 0, 0),
        )
        session = _mock_session(
            execute_results=[
                _FakeResult(scalar=7),  # 总数
                _FakeResult(rows=[batch_a, batch_b]),  # 时间倒序页
            ]
        )
        result = await attendance_import_service.list_ai_batches(
            session, page=1, page_size=20
        )
        assert result["total"] == 7
        assert [item["id"] for item in result["items"]] == [
            "batch-aaaaaaaa-1",
            "batch-bbbbbbbb-2",
        ]
        assert result["items"][0]["channel"] == "ai"
        assert result["items"][0]["created_at"] == "2026-10-18T10:00:00"
        assert result["items"][0]["fail_count"] == 1

    @pytest.mark.asyncio
    async def test_export_failure_rows_filters_failed(self):
        batch = AttendanceImportBatch(
            id="batch-1234-5678", tenant_id="t-1", channel="ai",
            file_key="file-1", status="parsed", operator_id="u-1",
            row_results=[
                {
                    "row_index": 2, "employee_no": "EMP0001", "employee_name": "张三",
                    "work_date": "2026-10-16", "parseable": True,
                },
                {
                    "row_index": 3, "employee_no": "EMP0002", "employee_name": "李四",
                    "work_date": "2026-10-16", "parseable": False,
                    "error": "未匹配员工",
                },
                {
                    "row_index": 4, "employee_no": "EMP0003", "employee_name": "王五",
                    "work_date": "bad-date", "parseable": True,
                    "error": "考勤日期格式无效",
                },
            ],
        )
        session = _mock_session(
            get_map={("AttendanceImportBatch", "batch-1234-5678"): batch}
        )
        filename, content = await attendance_import_service.export_failure_rows(
            session, "batch-1234-5678"
        )
        assert filename == "考勤导入失败明细-batch-12.xlsx"
        workbook = load_workbook(BytesIO(content))
        sheet = workbook.active
        assert sheet.title == "失败明细"
        rows = list(sheet.iter_rows(values_only=True))
        assert rows[0] == ("行号", "工号", "姓名", "考勤日期", "失败原因")
        assert len(rows) == 3  # 表头 + 2 条失败行（可解析无错误行不导出）
        assert rows[1] == (3, "EMP0002", "李四", "2026-10-16", "未匹配员工")
        assert rows[2] == (4, "EMP0003", "王五", "bad-date", "考勤日期格式无效")

    @pytest.mark.asyncio
    async def test_export_failure_rows_batch_not_found(self):
        session = _mock_session()
        with pytest.raises(NotFoundError):
            await attendance_import_service.export_failure_rows(session, "batch-404")
