"""考勤域任务消费者：AI 导入批次解析（LLM 结构化抽取回写批次）"""

from loguru import logger
from sqlalchemy import select

from framework.common.exceptions import BadRequestError
from framework.database.dependencies import get_listener_session
from framework.tasks import TaskConsumer, TaskContext, TaskRecord
from framework.tenant.context import TenantContext

from hr.models import AttendanceImportBatch
from hr.services.attendance_import_service import attendance_import_service

_logger = logger.bind(name=__name__)

ATTENDANCE_PARSE_TASK_TYPE = "hr_attendance_parse"
ATTENDANCE_PARSE_QUEUE = "hr-attendance"


class AttendanceParseConsumer(TaskConsumer):
    """考勤 AI 解析消费者：解析失败置批次 failed（可重试），异常向上抛由任务骨架重试。"""

    task_type = ATTENDANCE_PARSE_TASK_TYPE
    queue = ATTENDANCE_PARSE_QUEUE
    timeout_seconds = 300

    async def execute(self, task: TaskRecord, ctx: TaskContext) -> None:
        tenant_id = task.config_snapshot.get("tenant_id")
        batch_id = task.config_snapshot.get("batch_id")
        if not tenant_id or not batch_id:
            raise ValueError(f"任务配置缺失 batch_id/tenant_id: {task.config_snapshot}")

        await ctx.report_progress(30, "解析考勤文档")
        TenantContext.set_tenant_id(str(tenant_id))
        async with get_listener_session() as session:
            try:
                await attendance_import_service.parse_batch(session, str(batch_id))
            except BadRequestError:
                # LLM 输出异常等可定性失败：批次置 failed，走前端重试入口
                batch = (
                    await session.execute(
                        select(AttendanceImportBatch).where(
                            AttendanceImportBatch.id == str(batch_id)
                        )
                    )
                ).scalar_one_or_none()
                if batch:
                    batch.status = "failed"
                    await session.commit()
                _logger.warning(f"考勤 AI 解析定性失败 batch={batch_id}")
                return
            await session.commit()
        await ctx.report_progress(100, "解析完成")


_attendance_consumers: list[TaskConsumer] = []


async def setup_attendance_consumers() -> None:
    if _attendance_consumers:
        return
    consumers = [AttendanceParseConsumer()]
    for consumer in consumers:
        await consumer.start()
    _attendance_consumers.extend(consumers)


async def cleanup_attendance_consumers() -> None:
    for consumer in _attendance_consumers:
        await consumer.stop()
    _attendance_consumers.clear()
