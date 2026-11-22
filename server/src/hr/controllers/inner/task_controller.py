"""hr inner 定时任务触发面（task/listener 瘦身：任务 inner 化）

平台 task 进程薄壳按周期 POST 本面触发；业务执行在本进程（hr-api 侧）
后台运行，分布式锁/租户遍历在任务函数内自管。无认证（/*/inner/* 惯例）。
"""

from fastapi import APIRouter, HTTPException

from framework.tasks.background import spawn_background
from hr.tasks.services.channel_sync_task import run_channel_sync_task
from hr.tasks.services.contract_expiry_task import run_contract_expiry_task
from hr.tasks.services.report_snapshot_task import run_report_snapshot_task

router = APIRouter(prefix="/inner/v1")

_TASK_FUNCS = {
    "channel-sync": ("hr_channel_sync", run_channel_sync_task),
    "contract-expiry": ("hr_contract_expiry", run_contract_expiry_task),
    "report-snapshot": ("hr_report_snapshot", run_report_snapshot_task),
}


@router.post(
    "/tasks/{task_name}",
    tags=["hr-tasks"],
    summary="触发 hr 定时任务（后台执行立即返回；任务名白名单）。",
)
async def trigger_task(task_name: str) -> dict:
    entry = _TASK_FUNCS.get(task_name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"未知任务: {task_name}")
    task_id, func = entry
    spawn_background(task_id, func())
    return {"task": task_id, "triggered": True}
