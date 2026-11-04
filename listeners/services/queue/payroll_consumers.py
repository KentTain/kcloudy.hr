"""发薪试算任务消费者（hr_payroll_calc / hr-payroll 队列）"""

from loguru import logger
from sqlalchemy import select

from framework.database.dependencies import get_listener_session
from framework.tenant.context import TenantContext
from framework.tasks import TaskConsumer, TaskContext, TaskRecord

from hr.models import PayrollRun
from hr.services.payroll_service import payroll_service

_logger = logger.bind(name=__name__)


class PayrollCalcConsumer(TaskConsumer):
    """发薪批次试算（创建批次后异步执行；失败可重试，draft 可重算）"""

    task_type = "hr_payroll_calc"
    queue = "hr-payroll"
    timeout_seconds = 600

    async def execute(self, task: TaskRecord, ctx: TaskContext) -> None:
        run_id = task.config_snapshot.get("run_id")
        tenant_id = task.config_snapshot.get("tenant_id")
        if not run_id or not tenant_id:
            raise ValueError(f"任务配置缺失 run_id/tenant_id: {task.config_snapshot}")
        TenantContext.set_tenant_id(str(tenant_id))
        try:
            async with get_listener_session() as session:
                run = (
                    await session.execute(
                        select(PayrollRun).where(PayrollRun.id == run_id)
                    )
                ).scalar_one_or_none()
                if run is None:
                    _logger.warning(f"发薪批次不存在，跳过试算 run={run_id}")
                    return
                await payroll_service.calculate_run(session, run_id)
                await session.commit()
        finally:
            TenantContext.clear()


payroll_calc_consumer = PayrollCalcConsumer()


async def setup_payroll_consumers() -> None:
    await payroll_calc_consumer.start()


async def cleanup_payroll_consumers() -> None:
    await payroll_calc_consumer.stop()
