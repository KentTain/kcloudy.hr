"""hr 模块定时任务注册"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from hr.tasks.services.channel_sync_task import run_channel_sync_task
from hr.tasks.services.contract_expiry_task import run_contract_expiry_task
from hr.tasks.services.report_snapshot_task import run_report_snapshot_task

_logger = logger.bind(name=__name__)

_local_scheduler: AsyncIOScheduler | None = None

# 本地任务: (func, task_id, trigger, trigger_args)
local_tasks: list[tuple] = [
    # 合同到期扫描：到期自动置 expired + 30 天窗口到期提醒站内信（每日 08:30）
    (run_contract_expiry_task, "hr_contract_expiry", "cron", {"hour": 8, "minute": 30}),
    # 渠道定时同步：跨租户扫描已发布渠道职位，按 sync_interval_minutes 控频归集
    (
        run_channel_sync_task,
        "hr_channel_sync",
        "cron",
        {"minute": "*/10"},
    ),
    # 报表快照：跨租户刷新人事域趋势快照缓存（近 12 月在编趋势+离职率序列，每日 07:50）
    (
        run_report_snapshot_task,
        "hr_report_snapshot",
        "cron",
        {"hour": 7, "minute": 50},
    ),
]


async def setup_tasks() -> None:
    """注册并启动本地调度器"""
    global _local_scheduler

    _local_scheduler = AsyncIOScheduler(
        timezone="Asia/Shanghai",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=60,
    )

    for func, task_id, trigger, trigger_args in local_tasks:
        _local_scheduler.add_job(
            func,
            trigger,
            id=task_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            **trigger_args,
        )
    _local_scheduler.start()
    _logger.info(f"hr 本地调度器已启动，共 {len(local_tasks)} 个任务")


async def cleanup_tasks() -> None:
    """优雅停止调度器"""
    if _local_scheduler and _local_scheduler.running:
        _local_scheduler.shutdown(wait=True)
    _logger.info("hr 调度器已停止")
