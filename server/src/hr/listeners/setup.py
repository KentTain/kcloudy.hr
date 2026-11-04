"""HR Listeners 生命周期管理

注册离职生效事件监听 + 招聘域任务消费者（渠道发布回写/AI 简历解析）+
发薪试算任务消费者 + 考勤 AI 解析任务消费者。
"""

import asyncio
import logging
from typing import TYPE_CHECKING

from framework.cache.redis_util import RedisUtil
from hr.listeners.handlers.event_handler import OffboardedEventHandler
from hr.listeners.services.queue.attendance_consumers import (
    cleanup_attendance_consumers,
    setup_attendance_consumers,
)
from hr.listeners.services.queue.payroll_consumers import (
    cleanup_payroll_consumers,
    setup_payroll_consumers,
)
from hr.listeners.services.queue.recruiting_consumers import (
    cleanup_recruiting_consumers,
    setup_recruiting_consumers,
)

if TYPE_CHECKING:
    from framework.configs.settings import Settings

_logger = logging.getLogger(__name__)

CONSUMER_GROUP = "hr_events_group"
CONSUMER_NAME = "hr_consumer"

STREAM_HANDLERS = [
    ("employee_offboarded_events", OffboardedEventHandler()),
]

_handlers: list = []
_running = False
_listen_task: asyncio.Task | None = None


async def setup_listeners(settings: "Settings") -> None:
    """创建消费者组并启动监听任务"""
    global _handlers, _running, _listen_task

    _handlers = [handler for _, handler in STREAM_HANDLERS]

    for stream_name, _ in STREAM_HANDLERS:
        try:
            await RedisUtil.xgroup_create(
                stream_name,
                CONSUMER_GROUP,
                id="0",
                mkstream=True,
            )
            _logger.info(f"创建消费者组: {stream_name} -> {CONSUMER_GROUP}")
        except Exception as e:
            _logger.debug(f"消费者组已存在或创建失败: {stream_name} -> {e}")

    _running = True
    _listen_task = asyncio.create_task(_listen_events())
    _logger.info("HR 事件监听器注册完成")

    # 招聘域任务消费者（hr-recruiting 队列：发布回写 + 简历解析）
    await setup_recruiting_consumers()

    # 发薪试算任务消费者（hr-payroll 队列）
    await setup_payroll_consumers()

    # 考勤 AI 解析任务消费者（hr-attendance 队列）
    await setup_attendance_consumers()


async def cleanup_listeners() -> None:
    """取消所有事件监听器"""
    global _running, _listen_task

    await cleanup_attendance_consumers()
    await cleanup_payroll_consumers()
    await cleanup_recruiting_consumers()

    _running = False

    if _listen_task:
        _listen_task.cancel()
        try:
            await _listen_task
        except asyncio.CancelledError:
            pass
        _listen_task = None

    _logger.info("HR 事件监听器清理完成")


async def _listen_events() -> None:
    """从 Redis Stream 读取事件并分发给处理器（失败不 ack 待重试）。"""
    global _running

    streams = {stream_name: ">" for stream_name, _ in STREAM_HANDLERS}
    handler_map = {stream_name: handler for stream_name, handler in STREAM_HANDLERS}

    while _running:
        try:
            messages = await RedisUtil.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams=streams,
                count=10,
                block=1000,
            )
            if not messages:
                continue

            for stream_name, stream_messages in messages:
                handler = handler_map.get(stream_name)
                if not handler:
                    continue
                for message_id, message_data in stream_messages:
                    try:
                        await handler.handle(message_data)
                        await RedisUtil.xack(stream_name, CONSUMER_GROUP, message_id)
                    except Exception as e:
                        _logger.exception(
                            f"处理事件失败: stream={stream_name}, "
                            f"message_id={message_id}, error={e}"
                        )
        except asyncio.CancelledError:
            _logger.info("HR 事件监听任务被取消")
            break
        except Exception as e:
            _logger.exception(f"HR 事件监听错误: {e}")
            await asyncio.sleep(1)
